from __future__ import annotations

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

def overlay(project, described, declared, named=lambda name: name) -> dict:
    carried = {origin.id: origin.segment for origin in declared.origins}
    seen: dict[str, dict[str, list[str]]] = {}
    for segment in described.segments:
        for node in segment.nodes:
            on = seen.setdefault(node.name, {}).setdefault(carried.get(segment.id, segment.id), [])
            if node.address and node.address not in on:
                on.append(node.address)
    nodes = {}
    for name, kind in _kinds(project).items():
        if kind == SWITCH:
            continue
        found = seen.get(named(name))
        nodes[name] = {"status": "running" if found is not None else "not reported",
                       "addresses": found or {}}
    return {"project_id": project["project_id"], "nodes": nodes}

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

def _raw(detection, *keys):
    found = detection.raw or {}
    for key in keys:
        found = found.get(key) if isinstance(found, dict) else None
    return found

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
    said = str(_raw(detection, "log", "syslog", "hostname") or "")
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
    _step(path, near, on or None)
    if arrived != on:
        if on and arrived:
            routers = sorted(name for name in transit if linked(name, on) and linked(name, arrived))
            _step(path, near, routers[0] if len(routers) == 1 else None)
        _step(path, near, arrived or None)
    _step(path, near, holder)
    if holder == gateway:
        upstream = declared.roles.get(sent.get("target", ""), "")
        _step(path, near, NAMED_ON if linked(gateway, NAMED_ON) and linked(upstream, NAMED_ON) else None)
        _step(path, near, upstream or None)
        holder = upstream
    if holder and holder != goal:
        shared = {segment.id for segment in declared.segments} | set(carried.values())
        for name in _inner(near, kinds, shared, holder, goal)[1:] or [None, goal]:
            _step(path, near, name)
    return path, source

def follow(project, declared, nodes, sent, detections, named=lambda name: name) -> dict:
    near, kinds = _wired(project), _kinds(project)
    target = sent.get("target") or "board"
    service = declared.compose.get(target, "")
    goal = service if service in kinds else declared.roles.get(target, "")
    path, source = _walk(near, kinds, declared, nodes, dict(sent, target=target), detections, goal)

    sensors = {declared.roles[sensing]: declared.roles.get(sensed, "")
               for sensing, sensed in sorted(declared.watches.items()) if sensing in declared.roles}
    watching = {watched: host for host, watched in sensors.items()}
    heard: dict[str, list] = {}
    for detection in detections:
        if detection.source == "suricata":
            heard.setdefault(_sensor_of(detection, sensors, named), []).append(detection)
    rules = sorted({_rule_id(d) for d in detections if d.source == "modsecurity"} - {""})
    logged = any(d.source == "modsecurity" for d in detections)
    verdict = _verdict(sent, rules, logged)
    status = sent.get("status") or _status_seen([d for d in detections if d.source == "suricata"])
    reached = _reached(verdict, status)

    hops, placed = [], set()
    for position, name in enumerate(path):
        if name is None:
            hops.append({"node": None, "kind": "unknown"})
            continue
        if kinds.get(name) == SWITCH:
            hops.append({"node": name, "kind": "segment"})
            continue
        hop = {"node": name, "kind": "host", "evidence": position == 0}
        if position == 0:
            hop["source"] = source or None
        if name in watching and watching[name] not in placed:
            alerts = heard.get(watching[name], [])
            hop.update(sensor=watching[name],
                       alerts=[{"signature": d.signature, "sid": _sid(d)} for d in alerts])
            hop["evidence"] = hop["evidence"] or bool(alerts)
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
    return {"source": sent["sender"], "address": source or None, "target": goal,
            "hops": hops, "elsewhere": elsewhere}
