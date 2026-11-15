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
CAPTIONS = ("internet", "dmz", "web", "database")
FORWARDED = "udp"

@dataclass(frozen=True)
class Learner:
    wargame: str
    hosts: dict[str, tuple[str, ...]]
    roles: dict[str, str]
    switches: dict[str, str]
    sensors: dict[str, str]
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
    put(LOG_STORE, LOG_SERVER)
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

    sensors = {roles[sensing]: (hosts.get(roles.get(sensed, "")) or ("",))[0]
               for sensing, sensed in sorted(declared.watches.items()) if sensing in roles}
    hidden = {name for site, domain in sites.items() if site != wargame for name in _parts(site, domain)}
    if not customers_prefer:
        hidden.add(CUSTOMERS)
    first = next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")
    prefers = {ATTACKER: (first,), CUSTOMERS: tuple(customers_prefer), "": (first,)}
    kinds = {ATTACKER: "kali", ROUTER: "router", WAF: "waf", sites[wargame]: "server", database: "database",
             LOG_SERVER: "logs"}
    return Learner(wargame=wargame, hosts={real: tuple(shown) for real, shown in hosts.items()}, roles=placed,
                   switches=switches, sensors=sensors, hidden=frozenset(hidden), prefers=prefers,
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
        if ATTACKER in names:
            found_captions[zone] = "internet"
        elif ROUTER in names:
            found_captions[zone] = "dmz"
        elif names & learner.named("database") and WAF not in names:
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

def _customers(learner, found, host: str) -> dict:
    head = link_heads(learner, found).get((CUSTOMERS, INTERNET))
    if head is None or CUSTOMERS not in learner.hosts.get(host, ()):
        return {}
    held = [one for one in found if one.host == host and _rank(one, learner.prefers[CUSTOMERS]) < len(
        learner.prefers[CUSTOMERS])]
    return {"address": head.address.partition("/")[0], "more": max(0, len(held) - 1)}

def graph(learner, wiring) -> dict:
    found = wiring.interfaces()
    heads = link_heads(learner, found)
    captioned = captions(learner, found)
    zones = [zone for zone in ordered(learner, found) if wiring.network(zone)]
    nodes = [{"id": SWITCH.format(zone=zone), "kind": "switch", "zone": zone} for zone in zones]
    edges = []
    drawn: dict[str, str] = {}
    for container in sorted(wiring.containers, key=lambda one: one.service):
        if container.sniffs:
            network = wiring.bridged(container.sniffs) or wiring.network(
                wiring.legs(container).get(container.sniffs, ""))
            if network is not None and network.key in zones:
                drawn[container.service] = SENSOR.format(service=container.service)
                nodes.append({"id": drawn[container.service], "kind": "sensor", "zone": network.key})
                edges.append({"source": drawn[container.service], "target": SWITCH.format(zone=network.key),
                              "kind": "mirror"})
            continue
        named = [shown for shown in learner.hosts.get(container.host, ()) if shown != CUSTOMERS]
        if not named or named[0] in learner.hidden:
            continue
        name, legs = named[0], wiring.legs(container)
        on = [zone for zone in zones if zone in legs.values()]
        if not on:
            continue
        drawn[container.service] = name
        nodes.append({"id": name, "kind": learner.kinds.get(name, "host"), "name": name, "zones": on,
                      "customers": _customers(learner, found, container.host)})
        for zone in on:
            head = heads.get((name, zone))
            edges.append({"source": name, "target": SWITCH.format(zone=zone), "kind": "link",
                          "address": head.address.partition("/")[0] if head else ""})
    logging = [drawn[one.service] for one in wiring.logging() if one.service in drawn]
    if logging:
        nodes.append({"id": LOG_SERVER, "kind": "logs", "name": LOG_SERVER,
                      "port": f"{wiring.port}/{FORWARDED}" if wiring.port else ""})
        edges += [{"source": source, "target": LOG_SERVER, "kind": "logs"} for source in logging]
    drawn_zones = [{"id": zone, "caption": captioned[zone],
                    "subnet": "" if captioned[zone] == "internet" else next(iter(wiring.network(zone).subnets), "")}
                   for zone in zones]
    laid_out(drawn_zones, nodes, edges)
    return {"zones": drawn_zones, "nodes": nodes,
            "edges": [{"id": f"{edge['kind']}:{edge['source']}:{edge['target']}", **edge} for edge in edges]}

ICON_HALF = 26
ROW = 150
HANG = 90
HANG_SPREAD = 160
HANG_ROOM = 120
OUTER = 170
OUTER_ROOM = 110
HALF = 90
GAP_HALF = 120
ZONE_GAP = 80
TOP = 100
FLOOR = 70
SENSOR_DROP = 90
SENSOR_SPREAD = 90
LANE_DROP = 60
LANE = 12
COLLECTOR_DROP = 80
END_SPREAD = 12
ACROSS = ("kali", "router", "waf", "server", "database")

def _across(node) -> tuple:
    return (ACROSS.index(node["kind"]) if node["kind"] in ACROSS else len(ACROSS), node["id"])

def laid_out(zones, nodes, edges) -> None:
    order = [zone["id"] for zone in zones]
    index = {zone: at for at, zone in enumerate(order)}
    devices = sorted((node for node in nodes if node.get("zones")), key=_across)
    alone = {zone: [node for node in devices if node["zones"] == [zone]] for zone in order}
    between = {at: [node for node in devices if len(node["zones"]) > 1
                    and min(index[zone] for zone in node["zones"]) == at] for at in range(len(order))}
    at_x: dict[str, int] = {}
    edges_of_zone: dict[str, tuple[int, int]] = {}
    gaps: list[int] = []
    left = 0
    for at, zone in enumerate(order):
        members = alone[zone]
        outer = members[:1] if at in (0, len(order) - 1) else []
        outward = -1 if at == 0 else 1
        hanging = members[len(outer):]
        offsets = [(-1 if k % 2 == 0 else 1) * (HANG + HANG_SPREAD * (k // 2)) for k in range(len(hanging))]
        reach_left = max([HALF] + [-dx + HANG_ROOM for dx in offsets if dx < 0]
                         + [OUTER + OUTER_ROOM for _ in outer if outward < 0])
        reach_right = max([HALF] + [dx + HANG_ROOM for dx in offsets if dx > 0]
                          + [OUTER + OUTER_ROOM for _ in outer if outward > 0])
        bridge = left + reach_left
        at_x[SWITCH.format(zone=zone)] = bridge
        for node in outer:
            node.update(x=bridge + outward * OUTER, y=0, label="above")
        for node, dx in zip(hanging, offsets):
            node.update(x=bridge + dx, y=ROW, label="left" if dx < 0 else "right")
        edges_of_zone[zone] = (left, bridge + reach_right)
        right = bridge + reach_right
        if at < len(order) - 1 and between[at]:
            gap = right + GAP_HALF
            gaps.append(gap)
            for row, node in enumerate(between[at]):
                node.update(x=gap, y=row * ROW, label="above")
            left = gap + GAP_HALF
        else:
            left = right + ZONE_GAP
    for node in nodes:
        if node["kind"] == "switch":
            node.update(x=at_x[node["id"]], y=0)
    bottom = max([0] + [node["y"] for node in devices if "y" in node]) + FLOOR
    for zone in zones:
        x1, x2 = edges_of_zone[zone["id"]]
        zone["box"] = [x1, -TOP, x2, bottom]
    sensor_y = bottom + SENSOR_DROP
    for zone in order:
        for k, node in enumerate(node for node in nodes if node["kind"] == "sensor" and node["zone"] == zone):
            node.update(x=at_x[SWITCH.format(zone=zone)] + k * SENSOR_SPREAD, y=sensor_y, label="right")
    where = {node["id"]: node for node in nodes}
    logs = [edge for edge in edges if edge["kind"] == "logs" and "x" in where.get(edge["source"], {})]
    collector = next((node for node in nodes if node["kind"] == "logs"), None)
    if collector is None:
        return
    sources = [where[edge["source"]]["x"] for edge in logs]
    middle = gaps[0] if gaps else round(sum(sources) / max(1, len(sources)))
    lanes_top = sensor_y + LANE_DROP
    sides: dict[int, list[dict]] = {-1: [], 0: [], 1: []}
    for edge in logs:
        x = where[edge["source"]]["x"]
        sides[(x > middle) - (x < middle)].append(edge)
    lanes = 0
    for side, held in sides.items():
        held.sort(key=lambda edge: abs(where[edge["source"]]["x"] - middle))
        for k, edge in enumerate(held):
            source = where[edge["source"]]
            lane = lanes_top + (2 * k + (side > 0)) * LANE
            end = middle + side * END_SPREAD * (k + 1)
            edge.update(route=[[source["x"], lane], [end, lane]], end=[end - middle, -ICON_HALF])
            lanes = max(lanes, 2 * k + 2)
    collector.update(x=middle, y=lanes_top + max(0, lanes - 1) * LANE + COLLECTOR_DROP, label="below")
