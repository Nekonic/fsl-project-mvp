from __future__ import annotations

import ipaddress
import json
import uuid
from dataclasses import dataclass
from xml.etree import ElementTree

from range.interfaces import BRIDGE_PREFIX
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

SWITCH = "ethernet_switch"
BLOCKING_RULE = "949110"
UPSTREAM_FAILED = {502, 503, 504}
TRANSIT = ("edge", "gateway", "wargames")
SEEN_KEPT = 5
CONSOLE = "console"
DATABASE_SUFFIX = "-db"
SWITCH_SUFFIX = "-sw"
BRIDGE_SUFFIX = "-default"
LOG_STORE = "fsl-elasticsearch"
ATTACKER = "attacker"
CUSTOMERS = "customers"
FIREWALL = "firewall"
WAF = "waf"
LOG_SERVER = "log-server"
INTERNET = "internet"
SERVICE = "service-sw"
MONITORING = "monitoring-sw"
DISPLAY_IMAGE = "busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"

@dataclass(frozen=True)
class Learner:
    wargame: str
    hosts: dict[str, tuple[str, ...]]
    roles: dict[str, str]
    switches: dict[str, str]
    shared: frozenset[str]
    sensors: dict[str, str]
    hidden: frozenset[str]
    prefers: dict[str, tuple[str, ...]]

    def shown(self, real: str) -> str:
        return (self.hosts.get(real) or (real,))[0]

def domains(declared) -> dict[str, str]:
    gateway = declared.hosts.get(declared.roles.get("gateway", ""))
    return {name.split(".")[0]: name for name in (gateway.names if gateway else ())}

def _parts(wargame: str, domain: str) -> set[str]:
    database = f"{wargame}{DATABASE_SUFFIX}"
    return {domain, database, f"{database}{SWITCH_SUFFIX}"}

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
    put(roles.get("edge", ""), FIREWALL)
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

    switches = {origin.id: INTERNET for origin in declared.origins}
    switches.update({origin.segment: INTERNET for origin in declared.origins})
    switches[NAMED_ON] = SERVICE
    shared = frozenset(switches.values())
    switches[f"{wargame}{BRIDGE_SUFFIX}"] = f"{database}{SWITCH_SUFFIX}"

    sensors = {roles[sensing]: (hosts.get(roles.get(sensed, "")) or ("",))[0]
               for sensing, sensed in sorted(declared.watches.items()) if sensing in roles}
    hidden = {name for site, domain in sites.items() if site != wargame for name in _parts(site, domain)}
    if not customers_prefer:
        hidden.add(CUSTOMERS)
    first = next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")
    prefers = {ATTACKER: (first,), CUSTOMERS: tuple(customers_prefer), "": (first,)}
    return Learner(wargame=wargame, hosts={real: tuple(shown) for real, shown in hosts.items()}, roles=placed,
                   switches=switches, shared=shared, sensors=sensors, hidden=frozenset(hidden), prefers=prefers)

def _wired(project) -> dict[str, set[str]]:
    named = {node["node_id"]: node["name"] for node in project["topology"]["nodes"]}
    near = {name: set() for name in named.values()}
    for link in project["topology"]["links"]:
        one, other = (named[end["node_id"]] for end in link["nodes"])
        near[one].add(other)
        near[other].add(one)
    return near

def _kinds(project) -> dict[str, str]:
    return {node["name"]: node["node_type"] for node in project["topology"]["nodes"]}

def overlay(project, described, learner, beside=()) -> dict:
    seen: dict[str, dict[str, list[str]]] = {}
    for segment in described.segments:
        on = learner.switches.get(segment.id, segment.id)
        for node in segment.nodes:
            for shown in (learner.hosts.get(node.name) or (node.name,)):
                held = seen.setdefault(shown, {}).setdefault(on, [])
                if node.address and node.address not in held:
                    held.append(node.address)
    nodes = {}
    for name, kind in [*_kinds(project).items(), *((host, "") for host in beside)]:
        if kind == SWITCH:
            continue
        found = seen.get(name)
        nodes[name] = {"status": "running" if found is not None else "not reported",
                       "addresses": found or {}}
    return {"project_id": project["project_id"], "nodes": nodes}

def shown(drawn, project) -> dict:
    kinds = _kinds(project)
    return {**drawn, "nodes": {
        name: {**node, "addresses": {on: held for on, held in node["addresses"].items() if kinds.get(on) == SWITCH}}
        for name, node in drawn["nodes"].items() if name in kinds}}

def _inner(near, kinds, shared, start, goal) -> list[str]:
    came = {start: None}
    frontier = [start]
    while frontier:
        reached = []
        for name in frontier:
            if name == goal:
                path = [name]
                while came[path[-1]] is not None:
                    path.append(came[path[-1]])
                return path[::-1]
            for other in sorted(near[name]):
                if other in came or other in shared or (other != goal and kinds[other] != SWITCH):
                    continue
                came[other] = name
                reached.append(other)
        frontier = reached
    return []

def _dig(found, *keys):
    for key in keys:
        found = found.get(key) if isinstance(found, dict) else None
    return found

def _raw(detection, *keys):
    return _dig(detection.raw or {}, *keys)

def _rule_id(detection) -> str:
    return str(_raw(detection, "details", "ruleId") or "")

def _sid(detection):
    return _raw(detection, "alert", "signature_id")

def _status_seen(detections):
    return next((_raw(d, "http", "status") for d in detections if _raw(d, "http", "status")), None)

def _held(nodes, address) -> tuple[str, str]:
    for name, node in nodes.items():
        for segment, addresses in node["addresses"].items():
            if address and address in addresses:
                return name, segment
    return "", ""

def _addresses(nodes, name, segment) -> list[str]:
    return ((nodes.get(name) or {}).get("addresses") or {}).get(segment) or []

def _sensor_of(detection, sensors, named) -> str:
    return _said_by(detection.raw or {}, sensors, named)

def _said_by(raw, sensors, named) -> str:
    said = str(_dig(raw, "log", "syslog", "hostname") or "")
    if said:
        return next((host for host in sensors if named(host) == said.split(".")[0]), "")
    return next(iter(sensors)) if len(sensors) == 1 else ""

def _verdict(sent, rules, logged) -> str | None:
    if sent.get("blocked") or BLOCKING_RULE in rules:
        return "blocked"
    if sent.get("status") or logged:
        return "passed"
    return None

def _reached(verdict, status) -> bool | None:
    if verdict == "blocked":
        return False
    if verdict == "passed" and status and status not in UPSTREAM_FAILED:
        return True
    return None

def _step(path, near, name) -> None:
    last = path[-1]
    if name is None:
        if last is not None:
            path.append(None)
        return
    if last is not None and name not in near.get(last, ()):
        path.append(None)
    path.append(name)

def _walk(near, kinds, learner, nodes, sent, detections, goal) -> tuple[list, str]:
    gateway = learner.roles["gateway"]
    transit = {learner.roles[role] for role in TRANSIT if role in learner.roles}
    named_on = learner.switches[NAMED_ON]
    sender = sent["sender"]

    def linked(one, other):
        return bool(one and other) and other in near.get(one, ())

    to = (sent.get("to") or next((str(found) for d in detections
                                  for found in (_raw(d, "dest_ip"), _raw(d, "host_ip")) if found), ""))
    holder, arrived = _held(nodes, to)
    holder = holder or gateway
    source = next((d.src_ip for d in detections if d.src_ip), "") or sent.get("source") or ""
    owner, left_on = _held(nodes, source)
    asked = sent.get("on") or ""
    on = learner.switches.get(asked, asked) or (left_on if owner == sender else "")
    if not on and arrived and _addresses(nodes, sender, arrived):
        on = arrived
    if sent["kind"] == "browse" and not source:
        source = next(iter(_addresses(nodes, sender, on)), "")
    if not arrived and on and sent["kind"] != "browse" and holder == gateway:
        arrived = on if _addresses(nodes, gateway, on) else named_on

    path = [sender]
    if sender in kinds:
        _step(path, near, on or None)
        if arrived != on:
            if on and arrived:
                routers = sorted(name for name in transit if linked(name, on) and linked(name, arrived))
                _step(path, near, routers[0] if len(routers) == 1 else None)
            _step(path, near, arrived or None)
        _step(path, near, holder)
    else:
        path.append(holder)
    if holder == gateway:
        upstream = learner.roles.get(sent.get("target", ""), "")
        _step(path, near, named_on if linked(gateway, named_on) and linked(upstream, named_on) else None)
        _step(path, near, upstream or None)
        holder = upstream
    if holder and holder != goal:
        for name in _inner(near, kinds, learner.shared, holder, goal)[1:] or [None, goal]:
            _step(path, near, name)
    return path, source

def _request_seen(event) -> dict:
    return {"src_ip": event.get("src_ip"), "dest_ip": event.get("dest_ip"), "dest_port": event.get("dest_port"),
            "method": _dig(event, "http", "http_method"), "url": _dig(event, "http", "url"),
            "status": _dig(event, "http", "status")}

def follow(project, learner, nodes, sent, detections, named=lambda name: name, seen=()) -> dict:
    near, kinds = _wired(project), _kinds(project)
    sender = learner.shown(sent["sender"])
    if sent["kind"] != "browse" and sender not in kinds:
        sender = learner.roles["attacker"]
    target = sent.get("target") if sent.get("target") in learner.roles else learner.wargame
    goal = learner.roles[target]
    path, source = _walk(near, kinds, learner, nodes, dict(sent, sender=sender, target=target), detections, goal)

    watching: dict[str, str] = {}
    for host, watched in sorted(learner.sensors.items()):
        watching.setdefault(watched, host)
    heard: dict[str, list] = {}
    for detection in detections:
        if detection.source == "suricata":
            heard.setdefault(_sensor_of(detection, learner.sensors, named), []).append(detection)
    saw: dict[str, list] = {}
    for event in seen:
        saw.setdefault(_said_by(event, learner.sensors, named), []).append(event)
    rules = sorted({_rule_id(d) for d in detections if d.source == "modsecurity"} - {""})
    logged = any(d.source == "modsecurity" for d in detections)
    verdict = _verdict(sent, rules, logged)
    status = (sent.get("status") or _status_seen([d for d in detections if d.source == "suricata"])
              or next((_dig(event, "http", "status") for event in seen if _dig(event, "http", "status")), None))
    reached = _reached(verdict, status)

    hops, placed = [], set()
    for position, name in enumerate(path):
        if name is None:
            hops.append({"node": None, "kind": "unknown"})
            continue
        if name not in kinds:
            hops.append({"node": None, "kind": CONSOLE, "evidence": True, "source": source or None})
            continue
        if kinds.get(name) == SWITCH:
            hops.append({"node": name, "kind": "segment"})
            continue
        hop = {"node": name, "kind": "host", "evidence": position == 0}
        if position == 0:
            hop["source"] = source or None
        if name in watching and watching[name] not in placed:
            alerts, requests = heard.get(watching[name], []), saw.get(watching[name], [])
            hop.update(sensor=name,
                       alerts=[{"signature": d.signature, "sid": _sid(d)} for d in alerts],
                       requests=len(requests), seen=[_request_seen(event) for event in requests[:SEEN_KEPT]])
            hop["evidence"] = hop["evidence"] or bool(alerts) or bool(requests)
            placed.add(watching[name])
        if name == learner.roles["gateway"] and "verdict" not in placed:
            hop.update(verdict=verdict, rules=rules)
            hop["evidence"] = hop["evidence"] or verdict is not None
            placed.add("verdict")
        if position == len(path) - 1:
            hop.update(status=status if reached else None, reached=reached)
            hop["evidence"] = hop["evidence"] or reached is not None
        hops.append(hop)

    elsewhere = [{"sensor": learner.sensors.get(host) or None, "signature": d.signature, "sid": _sid(d)}
                 for host, found in sorted(heard.items()) if host not in placed for d in found]
    return {"source": sender if sender in kinds else CONSOLE, "address": source or None,
            "target": goal, "hops": hops, "elsewhere": elsewhere}

def facts(project, learner) -> dict[str, list[str]]:
    near, kinds = _wired(project), _kinds(project)
    entered = {name for name in near.get(INTERNET, ()) if kinds[name] != SWITCH}
    transit = [learner.roles[role] for role in TRANSIT if learner.roles.get(role) in entered]
    database = learner.roles.get(f"{learner.wargame}{DATABASE_SUFFIX}", "")
    return {
        "entry": transit[:1],
        "logs": [name for name in kinds if name == LOG_SERVER],
        "segment": sorted(name for name in near.get(database, ()) if kinds[name] == SWITCH),
    }

LABEL_STYLE = "font-family: Noto Sans;font-size: 10.0;fill: #1b4f8a;fill-opacity: 1.0;"
SWITCH_LABEL_STYLE = "font-family: Noto Sans;font-size: 10.0;fill: #5b6770;fill-opacity: 1.0;"
STARTS = "text-anchor: start;"
ENDS = "text-anchor: end;"
SYMBOL_SIZE = 60
LABEL_GAP = 6
LABEL_RISE = 28
LABEL_FALL = 4
LABEL_SIDE = 9
LABEL_DROP = 4
LABEL_CLIMB = 22
KOREAN_SUFFIX = " ("
CAPTION_CHAR = 0.62
NETWORKS_JOINED = ", "

def renamed(value: str, salt: str) -> str:
    return str(uuid.uuid5(uuid.UUID(value), salt))

def _ip(one):
    return ipaddress.ip_interface(one.address).ip

def _rank(one, prefers) -> int:
    return next((at for at, subnet in enumerate(prefers) if subnet and _ip(one) in ipaddress.ip_network(subnet)),
                len(prefers))

def _head(found, prefers, strict=False):
    ranked = [one for one in found if not strict or _rank(one, prefers) < len(prefers)]
    return min(ranked, key=lambda one: (_rank(one, prefers), one.name, _ip(one)), default=None)

def leaving(node, other) -> tuple[int, int]:
    dx, dy = other["x"] - node["x"], other["y"] - node["y"]
    if abs(dx) >= abs(dy):
        return (1 if dx > 0 else -1), 0
    return 0, (1 if dy > 0 else -1)

def _placed_label(node, other) -> tuple[int, int, str]:
    half = SYMBOL_SIZE // 2
    across, down = leaving(node, other)
    beside = half + LABEL_FALL if other["y"] < node["y"] else half - LABEL_RISE
    if across > 0:
        return SYMBOL_SIZE + LABEL_GAP, beside, STARTS
    if across < 0:
        return -LABEL_GAP, beside, ENDS
    if down > 0:
        return half + LABEL_SIDE, SYMBOL_SIZE + LABEL_DROP, STARTS
    return half + LABEL_SIDE, -LABEL_CLIMB, STARTS

def _shape(drawing) -> tuple[ElementTree.Element, ElementTree.Element]:
    svg = ElementTree.fromstring(drawing["svg"])
    return svg, svg[0]

def _area(drawing) -> tuple[float, float, float, float]:
    svg, _ = _shape(drawing)
    return drawing["x"], drawing["y"], drawing["x"] + float(svg.get("width")), drawing["y"] + float(svg.get("height"))

def _within(x, y, area) -> bool:
    return area[0] <= x <= area[2] and area[1] <= y <= area[3]

def _smallest(x, y, zones):
    holding = [zone for zone in zones if _within(x, y, _area(zone))]
    return min(holding, key=lambda zone: (_area(zone)[2] - _area(zone)[0]) * (_area(zone)[3] - _area(zone)[1]),
               default=None)

def _zones(document) -> tuple[list, list]:
    drawings = document["topology"]["drawings"]
    return ([drawing for drawing in drawings if _shape(drawing)[1].tag == "rect"],
            [drawing for drawing in drawings if _shape(drawing)[1].tag == "text"])

def captions(document) -> dict[str, dict]:
    zones, texts = _zones(document)
    titled = {id(_smallest(text["x"], text["y"], zones)): text for text in texts}
    found = {}
    for node in document["topology"]["nodes"]:
        if node["node_type"] == SWITCH:
            zone = _smallest(node["x"] + SYMBOL_SIZE / 2, node["y"] + SYMBOL_SIZE / 2, zones)
            if zone is not None and id(zone) in titled:
                found[node["name"]] = titled[id(zone)]
    return found

def for_wargame(project, learner) -> dict:
    document = json.loads(json.dumps(project))
    topology = document["topology"]
    gone = {node["node_id"] for node in topology["nodes"] if node["name"] in learner.hidden}
    topology["nodes"] = [node for node in topology["nodes"] if node["node_id"] not in gone]
    topology["links"] = [link for link in topology["links"] if not {end["node_id"] for end in link["nodes"]} & gone]
    zones, texts = _zones(document)
    kept = [zone for zone in zones if any(_within(node["x"] + SYMBOL_SIZE / 2, node["y"] + SYMBOL_SIZE / 2,
                                                  _area(zone)) for node in topology["nodes"])]
    shown = {id(zone) for zone in kept} | {id(text) for text in texts if id(_smallest(text["x"], text["y"], zones))
                                           in {id(zone) for zone in kept}}
    topology["drawings"] = [drawing for drawing in topology["drawings"] if id(drawing) in shown]
    return document

def _captioned(drawing, networks) -> None:
    svg, text = _shape(drawing)
    added = " " + NETWORKS_JOINED.join(networks)
    text.text = (text.text or "") + added
    svg.set("width", str(round(float(svg.get("width")) + len(added) * float(text.get("font-size")) * CAPTION_CHAR)))
    drawing["svg"] = ElementTree.tostring(svg, encoding="unicode")

def labelled(project, learner, found, salt: str, called: str) -> dict:
    document = for_wargame(project, learner)
    document["project_id"] = renamed(document["project_id"], salt)
    base, korean, rest = document["name"].partition(KOREAN_SUFFIX)
    document["name"] = f"{base} {called}" + (korean + rest if korean else "")
    document["show_interface_labels"] = True
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    held: dict[tuple[str, str], list] = {}
    for one in found:
        switch = learner.switches.get(one.segment)
        if switch and not one.name.startswith(BRIDGE_PREFIX):
            for name in learner.hosts.get(one.host, ()):
                held.setdefault((name, switch), []).append(one)
    networks: dict[str, list[str]] = {}
    for link in document["topology"]["links"]:
        ends = [by_id[end["node_id"]] for end in link["nodes"]]
        for end, node, other in ((link["nodes"][0], ends[0], ends[1]), (link["nodes"][1], ends[1], ends[0])):
            switching = node["node_type"] == SWITCH
            prefers = learner.prefers.get(node["name"], learner.prefers[""])
            head = None if switching else _head(held.get((node["name"], other["name"]), []), prefers,
                                                 strict=node["name"] == CUSTOMERS)
            text = f"{head.name} .{str(_ip(head)).rsplit('.', 1)[1]}" if head else ""
            if head:
                network = str(ipaddress.ip_interface(head.address).network)
                if network not in networks.setdefault(other["name"], []):
                    networks[other["name"]].append(network)
            x, y, anchor = _placed_label(node, other)
            end["label"] = {"text": text, "style": (SWITCH_LABEL_STYLE if switching else LABEL_STYLE) + anchor,
                            "x": x, "y": y, "rotation": 0}
        link["link_id"] = renamed(link["link_id"], salt)
    for switch, caption in captions(document).items():
        if networks.get(switch):
            _captioned(caption, networks[switch])
    for node in document["topology"]["nodes"]:
        node["node_id"] = renamed(node["node_id"], salt)
    for link in document["topology"]["links"]:
        for end in link["nodes"]:
            end["node_id"] = renamed(end["node_id"], salt)
    for drawing in document["topology"]["drawings"]:
        drawing["drawing_id"] = renamed(drawing["drawing_id"], salt)
    return document
