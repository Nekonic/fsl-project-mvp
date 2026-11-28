from __future__ import annotations

import ipaddress
from dataclasses import dataclass


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

TRANSIT = ("edge", "waf", "wargames")
DATABASE_SUFFIX = "-db"
BACKEND_SUFFIX = "-backend"
LOG_STORE = "cr-elasticsearch"
ATTACKER = "kali"
ROUTER = "router"
WAF = "waf"
LOG_SERVER = "log-server"
INTERNET = "internet"
SERVICE = "dmz"
SWITCH = "switch:{zone}"
SENSOR = "sensor:{service}"
INLINE_SENSOR = "ids"
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
    gateway = declared.hosts.get(declared.roles.get("waf", ""))
    return {name.split(".")[0]: name for name in (gateway.names if gateway else ())}

def _parts(wargame: str, domain: str) -> set[str]:
    return {domain, f"{wargame}{DATABASE_SUFFIX}"}

def learner(declared, wargame: str) -> Learner:
    roles, compose = declared.roles, declared.compose
    sites = domains(declared)
    database = f"{wargame}{DATABASE_SUFFIX}"
    hosts: dict[str, list[str]] = {}

    def put(real, shown):
        if real and shown not in hosts.setdefault(real, []):
            hosts[real].append(shown)

    put(roles.get("attacker", ""), ATTACKER)
    put(roles.get("edge", ""), ROUTER)
    put(roles.get("waf", ""), WAF)
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
    put(roles.get(LOG_SERVER, ""), LOG_SERVER)
    for sensing, sensed in sorted(declared.watches.items()):
        if roles.get(sensing) and roles[sensing] not in hosts and roles.get(sensed) in hosts:
            put(roles[sensing], hosts[roles[sensed]][0])

    others = {name for site in sites if site != wargame for name in (site, f"{site}{DATABASE_SUFFIX}")}
    placed = {}
    for role, real in roles.items():
        shown = hosts.get(compose.get(role, "")) or hosts.get(real)
        if role not in others and shown:
            placed[role] = shown[0]

    backend = f"{wargame}{BACKEND_SUFFIX}"
    switches = {origin.id: INTERNET for origin in declared.origins}
    switches.update({origin.segment: INTERNET for origin in declared.origins})

    hidden = {name for site, domain in sites.items() if site != wargame for name in _parts(site, domain)}
    first = next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")
    prefers = {ATTACKER: (first,), "": (first,)}
    kinds = {ATTACKER: "kali", ROUTER: "router", WAF: "waf", LOG_SERVER: "logs",
             **{domain: "server" for domain in sites.values()},
             **{f"{site}{DATABASE_SUFFIX}": "database" for site in sites}}
    return Learner(wargame=wargame, hosts={real: tuple(shown) for real, shown in hosts.items()}, roles=placed,
                   switches=switches, hidden=frozenset(hidden), prefers=prefers,
                   zones={"internet": INTERNET, "service": SERVICE, "database": backend}, kinds=kinds)

def route(learner, site: str, start: str = ATTACKER, wiring=None) -> list[str]:
    passed = [learner.roles[role] for role in TRANSIT if role in learner.roles]
    gateway = learner.roles.get("waf")
    if wiring is not None and gateway in passed and _sensed(learner, wiring)[1]:
        passed.insert(passed.index(gateway) + 1, INLINE_SENSOR)
    return list(dict.fromkeys([start, *passed, site]))

def link_heads(learner, found) -> dict[tuple[str, str], object]:
    held: dict[tuple[str, str], list] = {}
    for one in found:
        switch = learner.switches.get(one.segment, one.segment)
        if switch and not one.sensor:
            for name in learner.hosts.get(one.host, ()):
                held.setdefault((name, switch), []).append(one)
    return {pair: head for pair, kept in held.items()
            if (head := _head(kept, learner.prefers.get(pair[0], learner.prefers[""])))}

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

def extra_addresses(found, one) -> int:
    return sum(1 for other in found if other.host == one.host and other.name == one.name) - 1


def addresses(learner, found) -> list[dict]:
    named = captions(learner, found)
    order = {zone: at for at, zone in enumerate(ordered(learner, found))}
    listed = [(host, learner.kinds.get(host, "host"), zone, one)
              for (host, zone), one in link_heads(learner, found).items()
              if host not in learner.hidden]
    listed += [(one.host, "sensor", one.segment, one) for one in found if one.sensor and one.segment in named]
    return [{"host": host, "kind": kind, "zone": named[zone], "address": one.address.partition("/")[0],
             "network": "" if named[zone] == "internet" else str(ipaddress.ip_interface(one.address).network),
             "more": extra_addresses(found, one),
             **({"owner": zone.removesuffix(BACKEND_SUFFIX)} if named[zone] == "database" else {})}
            for host, kind, zone, one in sorted(listed, key=lambda row: (order.get(row[2], len(order)), row[0]))]

def _ip(one):
    return ipaddress.ip_interface(one.address).ip

def _rank(one, prefers) -> int:
    return next((at for at, subnet in enumerate(prefers) if subnet and _ip(one) in ipaddress.ip_network(subnet)),
                len(prefers))

def _head(found, prefers):
    return min(found, key=lambda one: (_rank(one, prefers), one.name, _ip(one)), default=None)

def _link(source: str, zone: str, address: str, more: int = 0) -> dict:
    return {"source": source, "target": SWITCH.format(zone=zone), "kind": "link", "address": address,
            **({"more": more} if more else {})}

def _sensed(learner, wiring) -> tuple[dict[str, list[str]], dict[str, str]]:
    gateway = learner.roles.get("waf", "")
    sensors, wires = {}, {}
    for container in wiring.containers:
        if not container.sniffs:
            continue
        legs = wiring.legs(container)
        sensor = SENSOR.format(service=container.service)
        sensors[sensor] = [legs[name] for name in container.sniffs if legs.get(name)]
        for network in sensors[sensor]:
            if any(gateway in learner.hosts.get(other.host, ()) and network in wiring.legs(other).values()
                   for other in wiring.containers if other is not container):
                wires[network] = sensor
    return sensors, wires

def graph(learner, wiring) -> dict:
    found = wiring.interfaces()
    heads = link_heads(learner, found)
    captioned = captions(learner, found)
    sensors, wires = _sensed(learner, wiring)
    zones = [zone for zone in ordered(learner, found) if wiring.network(zone) and zone not in wires]
    nodes = [{"id": SWITCH.format(zone=zone), "kind": "switch", "zone": zone} for zone in zones]
    edges = []
    for sensor, networks in sorted(sensors.items()):
        kept = [network for network in networks if network in zones]
        if kept and any(network in wires for network in networks):
            nodes.append({"id": sensor, "kind": "sensor", "zone": kept[0]})
            edges += [{"source": sensor, "target": SWITCH.format(zone=zone), "kind": "link"} for zone in kept]
    drawn = {node["id"] for node in nodes}
    for container in sorted(wiring.containers, key=lambda one: one.service):
        named = list(learner.hosts.get(container.host, ()))
        if container.sniffs or not named:
            continue
        name, legs = named[0], wiring.legs(container)
        on = [zone for zone in zones if zone in legs.values()]
        through = [network for network in dict.fromkeys(legs.values()) if wires.get(network) in drawn]
        if not on and not through:
            continue
        held = {zone: heads.get((name, zone)) for zone in on + through}
        nodes.append({"id": name, "kind": learner.kinds.get(name, "host"), "name": name, "zones": on})
        for zone, head in held.items():
            edge = (_link(name, zone, head.address.partition("/")[0], extra_addresses(found, head)) if head
                    else _link(name, zone, ""))
            edges.append({**edge, "target": wires[zone]} if zone in through else edge)
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
LABEL_PAD = 20
CAPTION_CLEAR = 24
CAPTION_CHAR = 8
CAPTION_NAMES = {"internet": 51, "dmz": 33, "web": 95, "database": 44, "mgmt": 51}
SPAN = 170
ROW = 320
DB_ROW = 210
TIER = 220
SENSOR_DROP = 200
OFFSET = 22
BOX_GAP = 40
CLEAR = 24
ADDRESS_GAP = 6
ADDRESS_RISE = 13
CHAR_WIDTH = 8
MORE_CHARS = 5
LABEL_CLEAR = 16
BAND = "mgmt"


def _below(node) -> int:
    return ICON_HALF + (0 if node["kind"] == "switch" else LABEL_GAP + LINE)


def _width(text: str, more: int = 0) -> int:
    return (len(text) + (len(str(more)) + MORE_CHARS if more else 0)) * CHAR_WIDTH


def _reach(edge) -> int:
    return 2 * (ICON_HALF + ADDRESS_GAP) + _width(edge.get("address", ""), edge.get("more", 0)) + LABEL_CLEAR


def _beside(width: int) -> int:
    return ICON_HALF + ADDRESS_GAP + width if width else ICON_HALF


def _spans(label) -> tuple[int, int]:
    width = _width(label["text"], label.get("more", 0))
    return (label["x"], label["x"] + width) if label["label"] == "right" else (label["x"] - width, label["x"])


def _boxed(held, labels=()) -> list[int]:
    spans = [_spans(label) for label in labels]
    return [min([node["x"] - ICON_HALF - PAD for node in held] + [left - LABEL_PAD for left, _ in spans]),
            min([node["y"] - ICON_HALF - PAD for node in held] + [label["y"] - LINE // 2 - LABEL_PAD for label in labels]),
            max([node["x"] + ICON_HALF + PAD for node in held] + [right + LABEL_PAD for _, right in spans]),
            max([node["y"] + _below(node) + PAD for node in held]
                + [label["y"] + LINE // 2 + LABEL_PAD for label in labels])]


def _home(node) -> str | None:
    held = node.get("zones") or []
    if node["kind"] == "sensor":
        return (held or [node["zone"]])[0]
    return None if node["kind"] in ("switch", "router") or not held else held[0]


def _caption_width(zone) -> int:
    owner = zone.get("owner", "")
    return (CAPTION_NAMES.get(zone["caption"], CAPTION_NAMES["web"]) + 2 * PAD // 5
            + ((len(owner) + 1) * CAPTION_CHAR if owner else 0)
            + ((len(zone["subnet"]) + 1) * CAPTION_CHAR if zone["subnet"] else 0))


def laid_out(zones, nodes, edges) -> list[dict]:
    where = {node["id"]: node for node in nodes}
    by: dict[str, list[str]] = {}
    for zone in zones:
        by.setdefault(zone["caption"], []).append(zone["id"])
    homes = {node["id"]: _home(node) for node in nodes}
    held = {zone["id"]: [node for node in nodes if homes[node["id"]] == zone["id"]] for zone in zones}
    switch = {zone["id"]: where[SWITCH.format(zone=zone["id"])] for zone in zones}
    inet, dmz, web, band = (next(iter(by.get(caption, ())), None) for caption in ("internet", "dmz", "web", "mgmt"))
    links = [edge for edge in edges if edge["kind"] == "link"]
    reach = {(edge["source"], edge["target"]): max(SPAN, _reach(edge)) for edge in links}
    widths = {(edge["source"], edge["target"]): _width(edge["address"], edge.get("more", 0))
              for edge in links if edge.get("address")}

    def toward(node, zone):
        return reach.get((node["id"], switch[zone]["id"]), SPAN)

    right = 0
    if inet:
        apart = max([SPAN] + [toward(node, inet) for node in held[inet]])
        switch[inet].update(x=apart, y=0)
        for k, node in enumerate(held[inet]):
            node.update(x=apart - apart * (k + 1), y=0)
        right = apart + ICON_HALF + PAD
    routers = [node for node in nodes if node["kind"] == "router"]
    for node in routers:
        before = widths.get((node["id"], switch[inet]["id"]), 0) if inet else 0
        after = max([width for (source, target), width in widths.items()
                     if source == node["id"] and not (inet and target == switch[inet]["id"])], default=0)
        node.update(x=right + CLEAR + _beside(before), y=0)
        right = node["x"] + _beside(after) + CLEAR
    if not routers:
        right += BOX_GAP
    if dmz:
        switch[dmz].update(x=right + PAD + ICON_HALF, y=0)
        x = switch[dmz]["x"]
        for node in held[dmz]:
            x += toward(node, dmz)
            node.update(x=x, y=0)
        right = x
    titles = {zone["id"]: 2 * (_caption_width(zone) // 2 + CAPTION_CLEAR) for zone in zones}
    servers = [node for node in held.get(web, ()) if node["kind"] != "sensor"] if web else []
    inline = [node for node in held.get(web, ()) if node["kind"] == "sensor"] if web else []
    sensors = [node for node in nodes if node["kind"] == "sensor" and node not in inline]
    below = SENSOR_DROP if inline else 0
    others = [node for node in held.get(band, ()) if node["kind"] != "sensor"] if band else []
    single = len(servers) <= 1
    western = -(ICON_HALF + PAD) if inet else 0
    if band:
        tapping = max([SPAN] + [toward(node, band) for node in sensors]) if sensors else 0
        reaching = tapping + max(sum(toward(node, band) for node in others) + ICON_HALF + PAD, titles[band])
        hub = western + reaching
    else:
        hub = western + ICON_HALF + PAD
    lowest = ROW + below + max(len(servers) - 1, 0) * TIER + SENSOR_DROP
    if web:
        for node in inline:
            node.update(x=hub, y=ROW)
        switch[web].update(x=hub, y=ROW + below)
        out = max([SPAN] + [toward(node, web) for node in servers]) + (0 if single else BOX_GAP)
        for k, node in enumerate(servers):
            node.update(x=hub + out, y=ROW + below + k * TIER)
    east = max((node["x"] for node in nodes if "x" in node), default=0)
    for zone in by.get("database", ()):
        server = next((node for node in servers if zone in node["zones"]), None)
        if server is None:
            switch[zone].update(x=east + 2 * (ICON_HALF + PAD) + BOX_GAP, y=ROW)
            row = ROW
        else:
            width = max([0] + [widths.get((node["id"], switch[one]["id"]), 0)
                               for node in servers for one in by.get("database", ())])
            switch[zone].update(x=server["x"] + _beside(width) + LABEL_PAD + BOX_GAP + PAD + ICON_HALF,
                                y=server["y"])
            row = server["y"]
        x = switch[zone]["x"]
        for k, node in enumerate(held[zone]):
            if single:
                node.update(x=x, y=row + SENSOR_DROP * (k + 1))
                lowest = max(lowest, node["y"])
            else:
                x += toward(node, zone)
                node.update(x=x, y=row)
        east = max([east, x] + [node["x"] for node in held[zone]])
    if band:
        mgmt_row = ROW + max(len(servers) - 1, 0) * TIER + SENSOR_DROP
        for k, node in enumerate(sensors):
            node.update(x=hub + SPAN * k, y=mgmt_row)
        switch[band].update(x=hub - tapping if sensors else hub - SPAN, y=mgmt_row)
        x = switch[band]["x"]
        for node in others:
            x -= toward(node, band)
            node.update(x=x, y=mgmt_row)
    for node in nodes:
        node.setdefault("x", east)
        node.setdefault("y", lowest)
        if node["kind"] != "switch":
            node["label"] = "below"
    _routed(edges, where, switch, web, homes)
    dropping = _dropping(links, where, homes, dmz)
    labels = _sided(edges, where, homes)
    for zone in zones:
        zone["box"] = _boxed([switch[zone["id"]], *held[zone["id"]]],
                             [label for label in labels if label["zone"] == zone["id"]])
    boxes = {zone["id"]: zone["box"] for zone in zones}
    if dropping:
        top = boxes[dmz][3]
        floor = min([box[1] for zone, box in boxes.items() if zone not in (inet, dmz)] or [top + 2 * PAD])
        for k, edge in enumerate(dropping):
            level = top + (floor - top) * (k + 1) // (len(dropping) + 1)
            edge["route"] = [[edge["route"][0][0], level], [where[edge["target"]]["x"], level]]
    for zone in zones:
        _captioned(zone, edges, where, [other["box"] for other in zones if other is not zone])
    return labels


def _routed(edges, where, switch, web, homes) -> None:
    for edge in edges:
        source, target = where[edge["source"]], where[edge["target"]]
        if edge["kind"] != "link" or edge.get("route"):
            continue
        if web and edge["target"] == SWITCH.format(zone=web) and homes[edge["source"]] == web \
                and source["y"] > target["y"] and source["kind"] != "sensor":
            middle = target["x"] + ICON_HALF + CAPTION_CLEAR
            edge["route"] = [[middle, source["y"]], [middle, target["y"]]]
            edge["end"] = [ICON_HALF, 0]


def _dropping(links, where, homes, dmz) -> list[dict]:
    falling = sorted((edge for edge in links if dmz and homes[edge["source"]] == dmz
                      and where[edge["target"]]["y"] > where[edge["source"]]["y"]),
                     key=lambda edge: where[edge["target"]]["x"])
    turning = []
    for k, edge in enumerate(falling):
        source, target = where[edge["source"]], where[edge["target"]]
        shift = OFFSET * (2 * k - (len(falling) - 1))
        edge["start"] = [shift, ICON_HALF]
        edge["end"] = [0, -ICON_HALF]
        if target["x"] == source["x"] + shift:
            continue
        edge["route"] = [[source["x"] + shift, target["y"]], [target["x"], target["y"]]]
        turning.append(edge)
    return turning


def _points(edge, where) -> list[tuple[int, int]]:
    source, target = where[edge["source"]], where[edge["target"]]
    start = edge.get("start") or [0, 0]
    end = edge.get("end") or [0, 0]
    return ([(source["x"] + start[0], source["y"] + start[1])] + [tuple(point) for point in edge.get("route") or ()]
            + [(target["x"] + end[0], target["y"] + end[1])])


def _sided(edges, where, homes) -> list[dict]:
    placed = []
    for edge in edges:
        source = where[edge["source"]]
        if edge["kind"] != "link" or not edge.get("address"):
            continue
        points = _points(edge, where)
        (x0, y0), (x1, y1) = points[0], points[1]
        if abs(x1 - x0) >= abs(y1 - y0):
            side = "right" if x1 > x0 else "left"
            x = source["x"] + (1 if x1 > x0 else -1) * (ICON_HALF + ADDRESS_GAP)
            y = source["y"] - ADDRESS_RISE
        else:
            side = "left" if x0 < source["x"] else "right"
            x = x0 + (-1 if side == "left" else 1) * ADDRESS_GAP
            y = source["y"] + (_below(source) + ADDRESS_RISE if y1 > y0 else -ICON_HALF - ADDRESS_RISE)
        placed.append(_label(edge, x, y, side, homes[edge["source"]]))
    return placed


def _label(edge, x, y, side, zone) -> dict:
    return {"id": f"address:{edge['source']}:{edge['target']}", "kind": "address", "text": edge["address"],
            **({"more": edge["more"]} if edge.get("more") else {}),
            "x": round(x), "y": round(y), "label": side, "zone": zone}


def _captioned(zone, edges, where, others) -> None:
    x1, top, x2, _ = zone["box"]
    width = _caption_width(zone)
    if x2 - x1 < width + 2 * CAPTION_CLEAR:
        grow = width + 2 * CAPTION_CLEAR - (x2 - x1)
        bottom = zone["box"][3]
        tried = [[x1 - (grow + 1) // 2, top, x2 + (grow + 1) // 2, bottom], [x1, top, x2 + grow, bottom],
                 [x1 - grow, top, x2, bottom]]
        zone["box"][:] = next((box for box in tried if not any(
            _overlaps(box, [other[0] - BOX_GAP, other[1], other[2] + BOX_GAP, other[3]]) for other in others)), tried[0])
        x1, _, x2, _ = zone["box"]
    crossing = sorted(x0 for edge in edges for (x0, y0), (x1_, y1) in zip(_points(edge, where), _points(edge, where)[1:])
                      if x0 == x1_ and min(y0, y1) < top < max(y0, y1) and x1 < x0 < x2)
    half = width // 2 + CAPTION_CLEAR
    middle = (x1 + x2) // 2
    fences = [x1 - half, *crossing, x2 + half]
    spots = []
    for low, high in zip(fences, fences[1:]):
        lowest, highest = max(low + half, x1 + half), min(high - half, x2 - half)
        if lowest <= highest:
            spots.append(min(max(middle, lowest), highest))
    if not spots:
        left, right = [crossing[0] - 2 * half, top, x2, zone["box"][3]], [x1, top, crossing[-1] + 2 * half, zone["box"][3]]
        free = [box for box in (left, right)
                if not any(_overlaps(box, [other[0] - BOX_GAP, other[1], other[2] + BOX_GAP, other[3]]) for other in others)] \
            or [right]
        zone["box"][:] = min(free, key=lambda box: (max([box[2]] + [other[2] for other in others])
                                                     - min([box[0]] + [other[0] for other in others]), box[2] - box[0]))
        x1, _, x2, _ = zone["box"]
        spots = [x1 + half if zone["box"] == left else x2 - half]
    zone["shift"] = min(spots, key=lambda at: abs(at - middle)) - (x1 + x2) // 2


def _overlaps(one, other) -> bool:
    return one[0] < other[2] and other[0] < one[2] and one[1] < other[3] and other[1] < one[3]

ATTACK = "attack"
DEFENCE = "defence"
SIDES = (ATTACK, DEFENCE)
HIDDEN_FROM_ATTACK = ("sensor", "logs")


def for_side(drawn: dict, side: str) -> dict:
    if side not in SIDES:
        raise ValueError(f"a side is one of {SIDES}, got {side!r}")
    if side == DEFENCE:
        return drawn
    hidden = {node["id"] for node in drawn.get("nodes") or () if node.get("kind") in HIDDEN_FROM_ATTACK}
    return {
        **drawn,
        "nodes": [node for node in drawn.get("nodes") or () if not _touches(node["id"], hidden)],
        "edges": [edge for edge in drawn.get("edges") or ()
                  if edge.get("source") not in hidden and edge.get("target") not in hidden],
    }


def _touches(identifier: str, hidden: set[str]) -> bool:
    return identifier in hidden or any(f":{one}:" in f"{identifier}:" for one in hidden)
