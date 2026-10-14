from __future__ import annotations

import ipaddress
import json
import uuid
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
LOG_STORE = "elasticsearch"
CONSOLE = "console"
SITE_PORT = 80
DATABASE_PORT = 3306
DATABASE_SUFFIX = "-db"

def domains(declared) -> dict[str, str]:
    gateway = declared.hosts.get(declared.roles.get("gateway", ""))
    return {name.split(".")[0]: name for name in (gateway.names if gateway else ())}

def shown_as(declared) -> dict[str, str]:
    return {name: domain for role, domain in domains(declared).items()
            for name in (declared.compose.get(role, ""), declared.roles.get(role, ""))
            if name and name not in declared.hosts}

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

def overlay(project, described, declared, named=lambda name: name, beside=()) -> dict:
    carried = {origin.id: origin.segment for origin in declared.origins}
    called = shown_as(declared)
    seen: dict[str, dict[str, list[str]]] = {}
    for segment in described.segments:
        for node in segment.nodes:
            on = seen.setdefault(called.get(node.name, node.name), {}).setdefault(carried.get(segment.id, segment.id), [])
            if node.address and node.address not in on:
                on.append(node.address)
    nodes = {}
    for name, kind in [*_kinds(project).items(), *((host, "") for host in beside)]:
        if kind == SWITCH:
            continue
        found = seen.get(name, seen.get(named(name)))
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

def _walk(near, kinds, declared, nodes, sent, detections, goal) -> tuple[list, str]:
    carried = {origin.id: origin.segment for origin in declared.origins}
    gateway = declared.roles["gateway"]
    transit = {declared.roles[role] for role in TRANSIT if role in declared.roles}
    sender = sent["sender"]

    def linked(one, other):
        return bool(one and other) and other in near.get(one, ())

    to = (sent.get("to") or next((str(found) for d in detections
                                  for found in (_raw(d, "dest_ip"), _raw(d, "host_ip")) if found), ""))
    holder, arrived = _held(nodes, to)
    holder = holder or gateway
    source = next((d.src_ip for d in detections if d.src_ip), "") or sent.get("source") or ""
    owner, left_on = _held(nodes, source)
    on = carried.get(sent.get("on") or "", sent.get("on") or "") or (left_on if owner == sender else "")
    if not on and arrived and _addresses(nodes, sender, arrived):
        on = arrived
    if sent["kind"] == "browse" and not source:
        source = next(iter(_addresses(nodes, sender, on)), "")
    if not arrived and on and sent["kind"] != "browse" and holder == gateway:
        arrived = on if _addresses(nodes, gateway, on) else NAMED_ON

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
        upstream = declared.roles.get(sent.get("target", ""), "")
        upstream = shown_as(declared).get(upstream, upstream)
        _step(path, near, NAMED_ON if linked(gateway, NAMED_ON) and linked(upstream, NAMED_ON) else None)
        _step(path, near, upstream or None)
        holder = upstream
    if holder and holder != goal:
        shared = {segment.id for segment in declared.segments} | set(carried.values())
        for name in _inner(near, kinds, shared, holder, goal)[1:] or [None, goal]:
            _step(path, near, name)
    return path, source

def _request_seen(event) -> dict:
    return {"src_ip": event.get("src_ip"), "dest_ip": event.get("dest_ip"), "dest_port": event.get("dest_port"),
            "method": _dig(event, "http", "http_method"), "url": _dig(event, "http", "url"),
            "status": _dig(event, "http", "status")}

def follow(project, declared, nodes, sent, detections, named=lambda name: name, seen=()) -> dict:
    near, kinds = _wired(project), _kinds(project)
    if sent["kind"] != "browse" and sent["sender"] not in kinds:
        sent = dict(sent, sender=declared.roles["attacker"])
    target = sent.get("target") or "board"
    goal = _on_map(declared, kinds, target)
    path, source = _walk(near, kinds, declared, nodes, dict(sent, target=target), detections, goal)

    sensors = {declared.roles[sensing]: declared.roles.get(sensed, "")
               for sensing, sensed in sorted(declared.watches.items()) if sensing in declared.roles}
    watching = {watched: host for host, watched in sensors.items()}
    heard: dict[str, list] = {}
    for detection in detections:
        if detection.source == "suricata":
            heard.setdefault(_sensor_of(detection, sensors, named), []).append(detection)
    saw: dict[str, list] = {}
    for event in seen:
        saw.setdefault(_said_by(event, sensors, named), []).append(event)
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
            hop.update(sensor=watching[name],
                       alerts=[{"signature": d.signature, "sid": _sid(d)} for d in alerts],
                       requests=len(requests), seen=[_request_seen(event) for event in requests[:SEEN_KEPT]])
            hop["evidence"] = hop["evidence"] or bool(alerts) or bool(requests)
            placed.add(watching[name])
        if name == declared.roles["gateway"] and "verdict" not in placed:
            hop.update(verdict=verdict, rules=rules)
            hop["evidence"] = hop["evidence"] or verdict is not None
            placed.add("verdict")
        if position == len(path) - 1:
            hop.update(status=status if reached else None, reached=reached)
            hop["evidence"] = hop["evidence"] or reached is not None
        hops.append(hop)

    elsewhere = [{"sensor": host or None, "signature": d.signature, "sid": _sid(d)}
                 for host, found in sorted(heard.items()) if host not in placed for d in found]
    return {"source": sent["sender"] if sent["sender"] in kinds else CONSOLE, "address": source or None,
            "target": goal,
            "hops": hops, "elsewhere": elsewhere}

def _images(project) -> dict[str, str]:
    return {node["name"]: str((node.get("properties") or {}).get("image") or "")
            for node in project["topology"]["nodes"]}

def _on_map(declared, kinds, role) -> str:
    called = shown_as(declared)
    service = called.get(declared.compose.get(role, ""), declared.compose.get(role, ""))
    host = declared.roles.get(role, "")
    return service if service in kinds else called.get(host, host)

def facts(project, declared, scenario) -> dict[str, list[str]]:
    near, kinds = _wired(project), _kinds(project)
    outside = {origin.segment for origin in declared.origins} & set(kinds)
    entered = {name for segment in outside for name in near[segment] if kinds[name] != SWITCH}
    transit = [declared.roles[role] for role in TRANSIT if declared.roles.get(role) in entered]
    stores = sorted(name for name, image in _images(project).items() if LOG_STORE in image)
    database = _on_map(declared, kinds, f"{scenario}-db")
    return {
        "entry": transit[:1],
        "logs": stores or [declared.roles["scorer"]],
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

def renamed(value: str, salt: str) -> str:
    return str(uuid.uuid5(uuid.UUID(value), salt))

def _ip(one):
    return ipaddress.ip_interface(one.address).ip

def _head(found, first):
    return min(found, key=lambda one: (not first or _ip(one) not in ipaddress.ip_network(first), one.name, _ip(one)))

def _said(found, first) -> str:
    head = _head(found, first)
    return f"{head.name} .{str(_ip(head)).rsplit('.', 1)[1]}"

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

def captions(document) -> dict[str, dict]:
    drawings = document["topology"]["drawings"]
    zones = [drawing for drawing in drawings if _shape(drawing)[1].tag == "rect"]
    texts = [drawing for drawing in drawings if _shape(drawing)[1].tag == "text"]
    titled = {id(_smallest(text["x"], text["y"], zones)): text for text in texts}
    found = {}
    for node in document["topology"]["nodes"]:
        if node["node_type"] == SWITCH:
            zone = _smallest(node["x"] + SYMBOL_SIZE / 2, node["y"] + SYMBOL_SIZE / 2, zones)
            if zone is not None and id(zone) in titled:
                found[node["name"]] = titled[id(zone)]
    return found

def _networks(found, first) -> dict[str, str]:
    held: dict[str, list] = {}
    for one in found:
        if one.segment:
            held.setdefault(one.segment, []).append(one)
    return {segment: str(ipaddress.ip_interface(_head(ones, first).address).network) for segment, ones in held.items()}

def _captioned(drawing, network) -> None:
    svg, text = _shape(drawing)
    added = f" {network}"
    text.text = (text.text or "") + added
    svg.set("width", str(round(float(svg.get("width")) + len(added) * float(text.get("font-size")) * CAPTION_CHAR)))
    drawing["svg"] = ElementTree.tostring(svg, encoding="unicode")

def labelled(project, found, salt: str, called: str, first: str = "") -> dict:
    document = json.loads(json.dumps(project))
    document["project_id"] = renamed(document["project_id"], salt)
    base, korean, rest = document["name"].partition(KOREAN_SUFFIX)
    document["name"] = f"{base} {called}" + (korean + rest if korean else "")
    document["show_interface_labels"] = True
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    held: dict[tuple[str, str], list] = {}
    for one in found:
        if one.segment and not one.name.startswith(BRIDGE_PREFIX):
            held.setdefault((one.host, one.segment), []).append(one)
    for link in document["topology"]["links"]:
        ends = [by_id[end["node_id"]] for end in link["nodes"]]
        for end, node, other in ((link["nodes"][0], ends[0], ends[1]), (link["nodes"][1], ends[1], ends[0])):
            switching = node["node_type"] == SWITCH
            ours = held.get((node["name"], other["name"])) if not switching else None
            text = _said(ours, first) if ours else ""
            x, y, anchor = _placed_label(node, other)
            end["label"] = {"text": text, "style": (SWITCH_LABEL_STYLE if switching else LABEL_STYLE) + anchor,
                            "x": x, "y": y, "rotation": 0}
        link["link_id"] = renamed(link["link_id"], salt)
    networks = _networks(found, first)
    for segment, caption in captions(document).items():
        if segment in networks:
            _captioned(caption, networks[segment])
    for node in document["topology"]["nodes"]:
        node["node_id"] = renamed(node["node_id"], salt)
    for link in document["topology"]["links"]:
        for end in link["nodes"]:
            end["node_id"] = renamed(end["node_id"], salt)
    for drawing in document["topology"]["drawings"]:
        drawing["drawing_id"] = renamed(drawing["drawing_id"], salt)
    return document

def addressing(project, declared, found, first: str = "") -> dict:
    kinds = _kinds(project)
    order = [name for name, kind in kinds.items() if kind != SWITCH]
    held: dict[tuple[str, str, str], list] = {}
    for one in found:
        if kinds.get(one.host, SWITCH) != SWITCH and kinds.get(one.segment) == SWITCH:
            held.setdefault((one.host, one.name, one.segment), []).append(one)
    devices = []
    for (host, name, segment), ones in sorted(held.items(), key=lambda item: (order.index(item[0][0]), item[0][1])):
        head = _head(ones, first)
        devices.append({"device": host, "interface": name, "address": head.address, "segment": segment,
                        "gateway": next((one.gateway for one in ones if one.gateway), "")})
    gateway = declared.roles.get("gateway", "")
    services = [{"name": domain, "host": gateway, "port": SITE_PORT} for domain in domains(declared).values()]
    for role in domains(declared):
        database = f"{role}{DATABASE_SUFFIX}"
        if database in declared.roles:
            services.append({"name": declared.compose.get(database, database),
                             "host": _on_map(declared, kinds, database), "port": DATABASE_PORT})
    return {"devices": devices, "services": services}
