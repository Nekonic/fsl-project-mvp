from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from range.slot import NAMED_ON

def shape(described, declared=None) -> dict:
    sensor_host = (declared.roles.get("sensor", "") if declared else "")
    sides: dict[str, set[bool]] = {}
    for segment in described.segments:
        for node in segment.nodes:
            sides.setdefault(node.name, set()).add(segment.outside)

    watching = {sensor.watches: sensor.name for sensor in described.sensors}

    segments = []
    for segment in described.segments:
        nodes = sorted(
            (
                {
                    "name": node.name,
                    "address": node.address,
                    "crosses": sides.get(node.name) == {True, False},
                    "sensor": watching.get(node.name, ""),
                    "watches": node.name == sensor_host,
                }
                for node in segment.nodes
            ),
            key=lambda node: node["name"],
        )
        segments.append({
            "id": segment.id,
            "name": segment.name or segment.id,
            "network": segment.network,
            "subnet": segment.subnet,
            "gateway": segment.gateway,
            "outside": segment.outside,
            "label": segment.origin,
            "nodes": nodes,
            "sensor": next((node["sensor"] for node in nodes if node["sensor"]), ""),
        })

    return {
        "segments": sorted(segments, key=lambda s: (not s["outside"], s["id"])),
        "sensors": sorted(
            ({"name": s.name, "watches": s.watches} for s in described.sensors),
            key=lambda sensor: sensor["name"],
        ),
    }

TRANSIT = ("edge", "gateway", "wargames")
DATABASE_SUFFIX = "-db"
BACKEND_SUFFIX = "-default"
LOG_STORE = "cr-elasticsearch"
ATTACKER = "kali"
CUSTOMERS = "customers"
ROUTER = "router"
WAF = "waf"
LOG_SERVER = "log-server"
INTERNET = "internet"
SERVICE = NAMED_ON
SWITCH = "switch:{zone}"
SENSOR = "sensor:{service}"
CAPTIONS = ("internet", "dmz", "web", "database", "mgmt")

@dataclass(frozen=True)
class Learner:
    wargame: str
    hosts: dict[str, tuple[str, ...]]
    roles: dict[str, str]
    switches: dict[str, str]
    hidden: frozenset[str]
    prefers: dict[str, tuple[str, ...]]
    zones: dict[str, str]
    kinds: dict[str, str]

    def shown(self, real: str) -> str:
        return (self.hosts.get(real) or (real,))[0]

    def named(self, kind: str) -> set[str]:
        return {name for name, held in self.kinds.items() if held == kind}

def domains(declared) -> dict[str, str]:
    gateway = declared.hosts.get(declared.roles.get("gateway", ""))
    return {name.split(".")[0]: name for name in (gateway.names if gateway else ())}

def _parts(wargame: str, domain: str) -> set[str]:
    return {domain, f"{wargame}{DATABASE_SUFFIX}"}

def learner(declared, wargame: str, customers_from: str = "", customers_prefer: tuple[str, ...] = ()) -> Learner:
    roles, compose = declared.roles, declared.compose
    sites = domains(declared)
    database = f"{wargame}{DATABASE_SUFFIX}"
    hosts: dict[str, list[str]] = {}

    def put(real, shown):
        if real and shown not in hosts.setdefault(real, []):
            hosts[real].append(shown)

    put(roles.get("attacker", ""), ATTACKER)
    if customers_prefer:
        put(customers_from, CUSTOMERS)
    put(roles.get("edge", ""), ROUTER)
    put(roles.get("gateway", ""), WAF)
    for real in (compose.get(wargame, ""), roles.get(wargame, "")):
        put(real, sites[wargame])
    for real in (compose.get(database, ""), roles.get(database, "")):
        if real not in hosts:
            put(real, database)
    for site, domain in sorted(sites.items()):
        if site != wargame:
            put(compose.get(site, ""), domain)
            put(compose.get(f"{site}{DATABASE_SUFFIX}", ""), f"{site}{DATABASE_SUFFIX}")
    put(LOG_STORE, LOG_SERVER)
    put(compose.get(LOG_SERVER, ""), LOG_SERVER)
    for sensing, sensed in sorted(declared.watches.items()):
        if roles.get(sensing) and roles[sensing] not in hosts and roles.get(sensed) in hosts:
            put(roles[sensing], hosts[roles[sensed]][0])

    others = {name for site in sites if site != wargame for name in (site, f"{site}{DATABASE_SUFFIX}")}
    placed = {}
    for role, real in roles.items():
        shown = hosts.get(compose.get(role, "")) or hosts.get(real)
        if role not in others and shown:
            placed[role] = shown[0]
    if customers_prefer:
        placed[CUSTOMERS] = CUSTOMERS

    backend = f"{wargame}{BACKEND_SUFFIX}"
    switches = {origin.id: INTERNET for origin in declared.origins}
    switches.update({origin.segment: INTERNET for origin in declared.origins})

    hidden = {name for site, domain in sites.items() if site != wargame for name in _parts(site, domain)}
    if not customers_prefer:
        hidden.add(CUSTOMERS)
    first = next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")
    prefers = {ATTACKER: (first,), CUSTOMERS: tuple(customers_prefer), "": (first,)}
    kinds = {ATTACKER: "kali", ROUTER: "router", WAF: "waf", LOG_SERVER: "logs",
             **{domain: "server" for domain in sites.values()},
             **{f"{site}{DATABASE_SUFFIX}": "database" for site in sites}}
    return Learner(wargame=wargame, hosts={real: tuple(shown) for real, shown in hosts.items()}, roles=placed,
                   switches=switches, hidden=frozenset(hidden), prefers=prefers,
                   zones={"internet": INTERNET, "service": SERVICE, "database": backend}, kinds=kinds)

def hosts(learner) -> list[str]:
    return sorted({shown for names in learner.hosts.values() for shown in names
                   if shown != CUSTOMERS and shown not in learner.hidden})

def route(learner, site: str, start: str = ATTACKER) -> list[str]:
    return list(dict.fromkeys([start, *(learner.roles[role] for role in TRANSIT if role in learner.roles), site]))

def link_heads(learner, found) -> dict[tuple[str, str], object]:
    held: dict[tuple[str, str], list] = {}
    for one in found:
        switch = learner.switches.get(one.segment, one.segment)
        if switch:
            for name in learner.hosts.get(one.host, ()):
                held.setdefault((name, switch), []).append(one)
    return {pair: head for pair, kept in held.items()
            if (head := _head(kept, learner.prefers.get(pair[0], learner.prefers[""]), strict=pair[0] == CUSTOMERS))}

def captions(learner, found) -> dict[str, str]:
    members: dict[str, set[str]] = {}
    for name, zone in link_heads(learner, found):
        members.setdefault(zone, set()).add(name)
    found_captions = {}
    for zone, names in members.items():
        if zone == INTERNET or ATTACKER in names:
            found_captions[zone] = "internet"
        elif zone == SERVICE or ROUTER in names:
            found_captions[zone] = "dmz"
        elif zone == BAND or LOG_SERVER in names:
            found_captions[zone] = "mgmt"
        elif zone.endswith(BACKEND_SUFFIX) or names & learner.named("database") and WAF not in names:
            found_captions[zone] = "database"
        else:
            found_captions[zone] = "web"
    return found_captions

def ordered(learner, found) -> list[str]:
    named = captions(learner, found)
    return sorted(named, key=lambda zone: (CAPTIONS.index(named[zone]), zone))

def switch_of(learner, found, host: str, zone: str | None = None) -> str:
    on = {held for name, held in link_heads(learner, found) if name == host}
    asked = learner.zones.get(zone or "", zone or "")
    if asked in on:
        return asked
    return next((held for held in ordered(learner, found) if held in on), "")

def address(learner, found, host: str, zone: str | None = None) -> list[str]:
    one = link_heads(learner, found).get((host, switch_of(learner, found, host, zone)))
    return [one.address, one.address.partition("/")[0]] if one else []

def subnet(learner, found, host: str, zone: str | None = None) -> list[str]:
    one = link_heads(learner, found).get((host, switch_of(learner, found, host, zone)))
    return [str(ipaddress.ip_interface(one.address).network)] if one else []

def addresses(learner, found) -> list[dict]:
    named = captions(learner, found)
    order = {zone: at for at, zone in enumerate(ordered(learner, found))}
    return [{"host": host, "zone": named[zone], "address": one.address.partition("/")[0],
             "network": "" if named[zone] == "internet" else str(ipaddress.ip_interface(one.address).network)}
            for (host, zone), one in sorted(link_heads(learner, found).items(),
                                            key=lambda pair: (order.get(pair[0][1], len(order)), pair[0][0]))
            if host not in learner.hidden]

def _ip(one):
    return ipaddress.ip_interface(one.address).ip

def _rank(one, prefers) -> int:
    return next((at for at, subnet in enumerate(prefers) if subnet and _ip(one) in ipaddress.ip_network(subnet)),
                len(prefers))

def _head(found, prefers, strict=False):
    ranked = [one for one in found if not strict or _rank(one, prefers) < len(prefers)]
    return min(ranked, key=lambda one: (_rank(one, prefers), one.name, _ip(one)), default=None)

def _link(source: str, zone: str, address: str) -> dict:
    return {"source": source, "target": SWITCH.format(zone=zone), "kind": "link", "address": address}

def graph(learner, wiring) -> dict:
    found = wiring.interfaces()
    heads = link_heads(learner, found)
    captioned = captions(learner, found)
    zones = [zone for zone in ordered(learner, found) if wiring.network(zone)]
    nodes = [{"id": SWITCH.format(zone=zone), "kind": "switch", "zone": zone} for zone in zones]
    edges = []
    for container in sorted(wiring.containers, key=lambda one: one.service):
        if container.sniffs:
            legs = wiring.legs(container)
            mirrored = [network.key for name in container.sniffs
                        if (network := wiring.bridged(name) or wiring.network(legs.get(name, ""))) is not None
                        and network.key in zones]
            if mirrored:
                sensor = SENSOR.format(service=container.service)
                linked = [(legs[name], address.partition("/")[0]) for name, address in container.addresses
                          if legs.get(name) in zones and legs[name] not in mirrored]
                nodes.append({"id": sensor, "kind": "sensor", "zone": mirrored[0],
                              **({"zones": [zone for zone, _ in linked]} if linked else {})})
                edges += [{"source": sensor, "target": SWITCH.format(zone=zone), "kind": "mirror"}
                          for zone in mirrored]
                edges += [_link(sensor, zone, address) for zone, address in linked]
            continue
        named = [shown for shown in learner.hosts.get(container.host, ()) if shown != CUSTOMERS]
        if not named:
            continue
        name, legs = named[0], wiring.legs(container)
        on = [zone for zone in zones if zone in legs.values()]
        if not on:
            continue
        held = {zone: head.address.partition("/")[0] if (head := heads.get((name, zone))) else "" for zone in on}
        nodes.append({"id": name, "kind": learner.kinds.get(name, "host"), "name": name, "zones": on})
        edges += [_link(name, zone, address) for zone, address in held.items()]
    drawn_zones = [{"id": zone, "caption": captioned[zone],
                    "subnet": "" if captioned[zone] == "internet" else next(iter(wiring.network(zone).subnets), ""),
                    **({"owner": zone.removesuffix(BACKEND_SUFFIX)} if captioned[zone] == "database" else {})}
                   for zone in zones]
    nodes += laid_out(drawn_zones, nodes, edges)
    return {"zones": drawn_zones, "nodes": nodes,
            "edges": [{"id": f"{edge['kind']}:{edge['source']}:{edge['target']}", **edge} for edge in edges]}

ICON_HALF = 26
LINE = 21
LABEL_GAP = 8
PAD = 30
CAPTION_WIDTH = 250
CAPTION_CLEAR = 16
SPAN = 200
DB_SPAN = 230
TIER = 440
DROP = 480
DROP_ONE = 380
WEB_SPAN = 250
BAND_GAP = 90
BAND_DROP = -160
TURN = 34
OFFSET = 22
BOX_GAP = 20
ADDRESS_GAP = 6
ADDRESS_RISE = 13
CHAR_WIDTH = 8
BAND = "mgmt"


def _below(node) -> int:
    return ICON_HALF + (0 if node["kind"] == "switch" else LABEL_GAP + LINE)


def _width(text: str) -> int:
    return len(text) * CHAR_WIDTH


def _spans(label) -> tuple[int, int]:
    width = _width(label["text"])
    return (label["x"], label["x"] + width) if label["label"] == "right" else (label["x"] - width, label["x"])


def _boxed(held, labels=()) -> list[int]:
    spans = [_spans(label) for label in labels]
    x1 = min([node["x"] - ICON_HALF - PAD for node in held] + [left - ADDRESS_GAP for left, _ in spans])
    x2 = max([node["x"] + ICON_HALF + PAD for node in held] + [right + ADDRESS_GAP for _, right in spans])
    widen = max(0, CAPTION_WIDTH - (x2 - x1)) // 2
    return [x1 - widen, min(node["y"] for node in held) - ICON_HALF - PAD,
            x2 + widen, max([node["y"] + _below(node) + PAD for node in held]
                            + [label["y"] + LINE for label in labels])]


def _home(node, band) -> str | None:
    held = node.get("zones") or []
    if node["kind"] == "sensor":
        return band
    return None if node["kind"] in ("switch", "router") or not held else held[0]


def laid_out(zones, nodes, edges) -> list[dict]:
    where = {node["id"]: node for node in nodes}
    by: dict[str, list[str]] = {}
    for zone in zones:
        by.setdefault(zone["caption"], []).append(zone["id"])
    band = next(iter(by.get(BAND, ())), None)
    homes = {node["id"]: _home(node, band) for node in nodes}
    held = {zone["id"]: [node for node in nodes if homes[node["id"]] == zone["id"]] for zone in zones}
    switch = {zone["id"]: where[SWITCH.format(zone=zone["id"])] for zone in zones}
    inet, dmz, web = (next(iter(by.get(caption, ())), None) for caption in ("internet", "dmz", "web"))
    column = 0
    if inet:
        switch[inet].update(x=SPAN, y=0)
        for k, node in enumerate(held[inet]):
            node.update(x=SPAN - SPAN * (k + 1), y=0, label="below")
        column = SPAN
    for node in nodes:
        if node["kind"] == "router":
            node.update(x=column + SPAN, y=0, label="below")
            column += SPAN
    if dmz:
        switch[dmz].update(x=column + SPAN, y=0)
        for k, node in enumerate(held[dmz]):
            node.update(x=column + SPAN * (k + 2), y=0, label="below")
        column = max([column + SPAN] + [node["x"] for node in held[dmz]])
    if web:
        servers = held[web]
        drop = DROP if len(servers) > 1 else DROP_ONE
        switch[web].update(x=column if held.get(dmz) else column + SPAN, y=drop)
        for k, node in enumerate(servers):
            node.update(x=switch[web]["x"] + WEB_SPAN, y=drop + round((k - (len(servers) - 1) / 2) * TIER), label="below")
        for zone in by.get("database", ()):
            server = next((node for node in servers if zone in node["zones"]), None)
            at = server or {"x": switch[web]["x"] + WEB_SPAN, "y": drop}
            switch[zone].update(x=at["x"] + DB_SPAN, y=at["y"])
            for k, node in enumerate(held[zone]):
                node.update(x=switch[zone]["x"] + SPAN * (k + 1), y=at["y"], label="below")
    flow = [zone for zone in zones if zone["id"] != band]
    _routed(nodes, edges, where, switch, web, homes)
    labels = _sided(nodes, edges, where, homes)
    for zone in flow:
        zone["box"] = _boxed([switch[zone["id"]], *held[zone["id"]]],
                             [label for label in labels if label["zone"] == zone["id"]])
    if band is not None:
        bottom = max(zone["box"][3] for zone in flow)
        _banded(band, held, switch, where, edges, bottom, web)
        zone = next(zone for zone in zones if zone["id"] == band)
        zone["box"] = _boxed([switch[band], *held[band]],
                             [label for label in _sided(nodes, edges, where, homes) if label["zone"] == band])
        _turned(edges, where, zones, homes, dmz)
    for zone in zones:
        _captioned(zone, edges, where)
    entering = _entering(nodes, edges, where, homes, {zone["id"]: zone for zone in zones})
    return _sided(nodes, edges, where, homes) + entering


def _routed(nodes, edges, where, switch, web, homes) -> None:
    for edge in edges:
        source, target = where[edge["source"]], where[edge["target"]]
        if "x" not in source or "x" not in target or edge["kind"] != "link":
            continue
        if web and edge["target"] == SWITCH.format(zone=web) and homes[edge["source"]] == web \
                and source["y"] != target["y"]:
            if source["y"] > target["y"]:
                edge["route"] = [[target["x"], source["y"]]]
                edge["end"] = [0, ICON_HALF]
            else:
                middle = (source["x"] + target["x"]) // 2
                edge["route"] = [[middle, source["y"]], [middle, target["y"]]]
                edge["end"] = [ICON_HALF, 0]


def _banded(band, held, switch, where, edges, bottom, web) -> None:
    beside = switch[web] if web else {"x": 0, "y": bottom}
    y = beside["y"] + BAND_DROP
    sensors = [node for node in held[band] if node["kind"] == "sensor"]
    for k, node in enumerate(sensors):
        mirrors = [edge for edge in edges if edge["source"] == node["id"] and edge["kind"] == "mirror"]
        at = where[mirrors[0]["target"]] if mirrors else beside
        node.update(x=at["x"] - SPAN * (k + 1), y=y, label="below")
        for edge in mirrors:
            middle = (node["x"] + at["x"]) // 2
            edge["start"], edge["end"] = [ICON_HALF, 0], [-ICON_HALF, 0]
            edge["route"] = [[middle, node["y"]], [middle, at["y"]]]
    anchor = min([node["x"] for node in sensors] + [beside["x"]]) - SPAN
    switch[band].update(x=anchor, y=y)
    for k, node in enumerate(node for node in held[band] if node["kind"] != "sensor"):
        node.update(x=anchor - SPAN * (k + 1), y=y, label="below")


def _turned(edges, where, zones, homes, dmz) -> None:
    boxes = {zone["id"]: zone["box"] for zone in zones}
    for edge in edges:
        source, target = where[edge["source"]], where[edge["target"]]
        if edge["kind"] != "link" or homes[edge["source"]] != dmz or target["y"] <= source["y"]:
            continue
        if target["x"] == source["x"]:
            continue
        lower = [one for one in edges if one["source"] == edge["source"] and one is not edge
                 and one["kind"] == "link" and where[one["target"]]["y"] > source["y"]]
        edge["start"] = [-OFFSET, ICON_HALF]
        turn = boxes[dmz][3] + TURN
        edge["route"] = [[source["x"] - OFFSET, turn], [target["x"], turn]]
        for one in lower:
            if where[one["target"]]["x"] == source["x"]:
                one["start"], one["end"] = [OFFSET, ICON_HALF], [OFFSET, -ICON_HALF]


def _points(edge, where) -> list[tuple[int, int]]:
    source, target = where[edge["source"]], where[edge["target"]]
    start = edge.get("start") or [0, 0]
    end = edge.get("end") or [0, 0]
    return ([(source["x"] + start[0], source["y"] + start[1])] + [tuple(point) for point in edge.get("route") or ()]
            + [(target["x"] + end[0], target["y"] + end[1])])


def _sided(nodes, edges, where, homes) -> list[dict]:
    placed = []
    for edge in edges:
        source, target = where[edge["source"]], where[edge["target"]]
        if edge["kind"] != "link" or not edge.get("address") or "x" not in source or "x" not in target:
            continue
        if homes[edge["source"]] not in (None, target["zone"]):
            continue
        points = _points(edge, where)
        (x0, y0), (x1, y1) = points[0], points[1]
        if abs(x1 - x0) >= abs(y1 - y0):
            side = "right" if x1 > x0 else "left"
            x = source["x"] + (1 if x1 > x0 else -1) * (ICON_HALF + ADDRESS_GAP)
            y = source["y"] - ADDRESS_RISE
        else:
            side, x = "right", x0 + ADDRESS_GAP
            y = source["y"] + (_below(source) + ADDRESS_RISE if y1 > y0 else -ICON_HALF - ADDRESS_RISE)
        placed.append(_label(edge, edge["address"], x, y, side, target["zone"]))
    return placed


def _label(edge, text, x, y, side, zone) -> dict:
    return {"id": f"address:{edge['source']}:{edge['target']}", "kind": "address", "text": text,
            "x": round(x), "y": round(y), "label": side, "zone": zone}


def _entering(nodes, edges, where, homes, boxes) -> list[dict]:
    placed = []
    for edge in edges:
        source, target = where[edge["source"]], where[edge["target"]]
        home = homes[edge["source"]]
        if edge["kind"] != "link" or not edge.get("address") or home in (None, target["zone"]):
            continue
        box = boxes[target["zone"]]["box"]
        if source["y"] == target["y"] and source["x"] < box[0]:
            box[0] = min(box[0], boxes[home]["box"][2] + BOX_GAP)
        points = _points(edge, where)
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 == x1 and y0 < box[1] <= y1:
                box[1] = min(box[1], target["y"] - ICON_HALF - 2 * LINE - ADDRESS_GAP)
                placed.append(_label(edge, edge["address"], x0 + ADDRESS_GAP, box[1] + LINE + ADDRESS_GAP // 2,
                                     "right", target["zone"]))
                break
            if y0 == y1 and x0 < box[0] <= x1:
                placed.append(_label(edge, edge["address"], box[0] + ADDRESS_GAP, y0 - ADDRESS_RISE, "right",
                                     target["zone"]))
                break
    return placed


def _captioned(zone, edges, where) -> None:
    x1, top, x2, _ = zone["box"]
    crossing = sorted(x0 for edge in edges for (x0, y0), (x1_, y1) in zip(_points(edge, where), _points(edge, where)[1:])
                      if x0 == x1_ and min(y0, y1) < top < max(y0, y1) and x1 < x0 < x2)
    half = CAPTION_WIDTH // 2
    middle = (x1 + x2) // 2
    clear = lambda at: all(abs(at - x) >= half + CAPTION_CLEAR for x in crossing)
    if crossing and not any(clear(at) for at in (middle, x1 + half + CAPTION_CLEAR, x2 - half - CAPTION_CLEAR)):
        right = crossing[-1] + CAPTION_CLEAR + CAPTION_WIDTH + CAPTION_CLEAR
        left = crossing[0] - CAPTION_CLEAR - CAPTION_WIDTH - CAPTION_CLEAR
        if right - x2 <= x1 - left:
            zone["box"][2] = x2 = right
        else:
            zone["box"][0] = x1 = left
        middle = (x1 + x2) // 2
    candidates = [middle, x1 + half + CAPTION_CLEAR, x2 - half - CAPTION_CLEAR]
    zone["shift"] = next((at for at in candidates if clear(at)), middle) - middle
