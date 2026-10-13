from __future__ import annotations

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

def _route(near, kinds, transit, start, goal) -> list[str]:
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
            if name != start and kinds[name] != SWITCH and name not in transit:
                continue
            for other in sorted(near[name]):
                if other not in came:
                    came[other] = name
                    reached.append(other)
        frontier = reached
    return []

def _rule_id(detection) -> str:
    return str(((detection.raw or {}).get("details") or {}).get("ruleId") or "")

def _sid(detection):
    return ((detection.raw or {}).get("alert") or {}).get("signature_id")

def _status_seen(detections):
    return next((((d.raw or {}).get("http") or {}).get("status") for d in detections
                 if ((d.raw or {}).get("http") or {}).get("status")), None)

def _origin(nodes, declared, source_ip) -> list[str]:
    for name, node in nodes.items():
        for segment, addresses in node["addresses"].items():
            if source_ip in addresses:
                return [name, segment]
    carried = {origin.id: origin.segment for origin in declared.origins}
    outside = next((s.id for s in declared.segments if s.outside), "")
    return [carried.get(outside, outside)]

def follow(project, declared, nodes, detections, record=None, target="board") -> dict:
    near, kinds = _wired(project), _kinds(project)
    source_ip = next((d.src_ip for d in detections if d.src_ip), "")
    origin = _origin(nodes, declared, source_ip)
    gateway = declared.roles["gateway"]
    service = declared.compose.get(target, "")
    goal = service if service in kinds else declared.roles.get(target, "")
    transit = {declared.roles[role] for role in ("edge", "gateway", "wargames") if role in declared.roles}
    there = _route(near, kinds, transit, origin[-1], gateway)
    onward = _route(near, kinds, transit, gateway, goal)
    path = origin[:-1] + there + onward[1:] if there and onward else []

    watched = declared.roles.get(declared.watches.get("sensor", ""), "")
    sensed = [d for d in detections if d.source == "suricata"]
    rules = sorted({_rule_id(d) for d in detections if d.source == "modsecurity"} - {""})
    blocked = bool(record and record.get("blocked")) or BLOCKING_RULE in rules
    status = record.get("status") if record else _status_seen(sensed)
    hops, told = [], set()
    for position, name in enumerate(path):
        hop = {"node": name, "kind": "segment" if kinds[name] == SWITCH else "host"}
        if position == 0:
            hop["source"] = source_ip
        if name == watched and "alerts" not in told:
            hop["alerts"] = [{"signature": d.signature, "sid": _sid(d)} for d in sensed]
            told.add("alerts")
        if name == gateway and "verdict" not in told:
            hop.update(verdict="blocked" if blocked else "passed", rules=rules)
            told.add("verdict")
        if position == len(path) - 1:
            hop.update(status=None if blocked else status, reached=not blocked)
        hops.append(hop)
    return {"source": origin[0], "target": goal, "hops": hops}
