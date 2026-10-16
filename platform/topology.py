from __future__ import annotations

import ipaddress
import json
import math
import re
import uuid
from dataclasses import dataclass
from xml.etree import ElementTree

from range.fabric import MANAGEMENT
from range.interfaces import BRIDGE_PREFIX, BUSYBOX
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
TRANSIT = ("edge", "gateway", "wargames")
DATABASE_SUFFIX = "-db"
BRIDGE_SUFFIX = "-default"
LOG_STORE = "fsl-elasticsearch"
ATTACKER = "kali"
CUSTOMERS = "customers"
FIREWALL = "firewall"
WAF = "waf"
LOG_SERVER = "log-server"
INTERNET = "internet"
ADDRESS_VARIES = frozenset({ATTACKER, CUSTOMERS})
SERVICE = "sw1"
DATABASE_SWITCH = "sw2"
MONITORING = "sw3"
SCORER = "scorer"
DISPLAY_IMAGE = BUSYBOX

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
    unaddressed: dict[str, str]
    logs_from: tuple[str, ...]

    def shown(self, real: str) -> str:
        return (self.hosts.get(real) or (real,))[0]

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
    switches[f"{wargame}{BRIDGE_SUFFIX}"] = DATABASE_SWITCH

    sensors = {roles[sensing]: (hosts.get(roles.get(sensed, "")) or ("",))[0]
               for sensing, sensed in sorted(declared.watches.items()) if sensing in roles}
    hidden = {name for site, domain in sites.items() if site != wargame for name in _parts(site, domain)}
    if not customers_prefer:
        hidden.add(CUSTOMERS)
    first = next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")
    prefers = {ATTACKER: (first,), CUSTOMERS: tuple(customers_prefer), "": (first,)}
    logs_from = tuple(dict.fromkeys(filter(None, (LOG_STORE, roles.get(SCORER, "")))))
    return Learner(wargame=wargame, hosts={real: tuple(shown) for real, shown in hosts.items()}, roles=placed,
                   switches=switches, shared=shared, sensors=sensors, hidden=frozenset(hidden), prefers=prefers,
                   unaddressed={MANAGEMENT: MONITORING}, logs_from=logs_from)

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

def overlay(project, described, learner) -> dict:
    seen: dict[str, dict[str, list[str]]] = {}
    for segment in described.segments:
        on = learner.switches.get(segment.id, segment.id)
        for node in segment.nodes:
            for shown in (learner.hosts.get(node.name) or (node.name,)):
                held = seen.setdefault(shown, {}).setdefault(on, [])
                if node.address and node.address not in held:
                    held.append(node.address)
    nodes = {}
    for name, kind in _kinds(project).items():
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
LABEL_RISE = 32
LABEL_FALL = 6
LABEL_ASIDE = 10
LABEL_BELOW = 64
LABEL_ABOVE = -60
LABEL_CHAR = 7
NAME_CHAR = 9
LABEL_CLEAR = 3
STATUS_MARK_ALONG = 60
STATUS_MARK_RADIUS = 6
GLYPH_TOP = 4
GLYPH_BOTTOM = 23
NAME_TOP = 1
NAME_BOTTOM = 22
LABEL_NUDGE = 3
PORT_NAME = re.compile(r"(?P<kind>[A-Za-z])[A-Za-z]*(?P<number>\d+)")
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

def heading(node, other) -> tuple[float, float]:
    dx, dy = other["x"] - node["x"], other["y"] - node["y"]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length

def _apart(one, other) -> float:
    return math.acos(max(-1.0, min(1.0, one[0] * other[0] + one[1] * other[1])))

def _roomier(sides, others):
    room = [min((_apart(side, other) for other in others), default=math.pi) for side in sides]
    return sides[1] if room[1] > room[0] else sides[0]

def named_above(node) -> bool:
    return (node.get("label") or {}).get("x") is None

def _box(x, y, anchor, width) -> tuple[float, float, float, float]:
    left = x + LABEL_NUDGE - (width if anchor == ENDS else 0)
    return left, y + GLYPH_TOP, left + width, y + GLYPH_BOTTOM

def label_box(label) -> tuple[float, float, float, float]:
    return _box(label["x"], label["y"], ENDS if ENDS in label["style"] else STARTS, len(label["text"]) * LABEL_CHAR)

def name_box(node) -> tuple[float, float, float, float]:
    label = node.get("label") or {}
    width = len(label.get("text") or "") * NAME_CHAR
    x = (SYMBOL_SIZE - width) / 2 if label.get("x") is None else label["x"]
    y = label.get("y") or 0
    return x + LABEL_NUDGE, y + NAME_TOP, x + LABEL_NUDGE + width, y + NAME_BOTTOM

def _covers(one, other) -> bool:
    return (one[0] - LABEL_CLEAR < other[2] and other[0] < one[2] + LABEL_CLEAR
            and one[1] - LABEL_CLEAR < other[3] and other[1] < one[3] + LABEL_CLEAR)

def _placed_label(node, other, others, text) -> tuple[int, int, str]:
    half = SYMBOL_SIZE // 2
    dx, dy = other["x"] - node["x"], other["y"] - node["y"]
    if abs(dx) >= abs(dy):
        near = half + LABEL_GAP
        mark = STATUS_MARK_ALONG * abs(dx) / math.hypot(dx, dy) + STATUS_MARK_RADIUS
        crossed = [half + dy / abs(dx) * reach for reach in (near, max(near + len(text) * LABEL_CHAR, mark))]
        under, over = (0, 1), (0, -1)
        first = _roomier((under, over) if dy < 0 else (over, under), others)
        placed = []
        for side in (first, under if first == over else over):
            y = round(min(crossed) - LABEL_RISE if side == over else max(crossed) + LABEL_FALL)
            placed.append((SYMBOL_SIZE + LABEL_GAP - LABEL_NUDGE, y, STARTS) if dx > 0
                          else (-LABEL_GAP - LABEL_NUDGE, y, ENDS))
        return next((one for one in placed if not _covers(_box(*one, len(text) * LABEL_CHAR), name_box(node))),
                    placed[0])
    if dy < 0 and named_above(node):
        return SYMBOL_SIZE + LABEL_GAP - LABEL_NUDGE, LABEL_FALL, STARTS
    top = LABEL_BELOW if dy > 0 else LABEL_ABOVE
    crossed = [half + dx / dy * (y - half)
               for y in (top + GLYPH_TOP - STATUS_MARK_RADIUS, top + GLYPH_BOTTOM + STATUS_MARK_RADIUS)]
    if _roomier(((1, 0), (-1, 0)), others) == (1, 0):
        return round(max(crossed) + LABEL_ASIDE) - LABEL_NUDGE, top, STARTS
    return round(min(crossed) - LABEL_ASIDE) - LABEL_NUDGE, top, ENDS

def port_label(node, number: int) -> str:
    named = next((port["name"] for port in (node.get("properties") or {}).get("ports_mapping") or ()
                  if port["port_number"] == number), "")
    found = PORT_NAME.fullmatch(named)
    return f"{found['kind'].lower()}{found['number']}" if found else ""

def _nic_only(learner, found) -> dict[tuple[str, str], str]:
    ranked: dict[tuple[str, str], list] = {}
    for one in found:
        switch = learner.unaddressed.get(one.segment)
        if not switch or one.name.startswith(BRIDGE_PREFIX):
            continue
        logging = one.host in learner.logs_from
        names = learner.hosts.get(one.host) or ((LOG_SERVER,) if logging else ())
        rank = learner.logs_from.index(one.host) if logging else 0
        for name in names:
            ranked.setdefault((name, switch), []).append((rank, one.name))
    return {pair: min(held)[1] for pair, held in ranked.items()}

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
    bare = _nic_only(learner, found)
    toward: dict[str, list[tuple[str, tuple[float, float]]]] = {}
    for link in document["topology"]["links"]:
        one, other = (by_id[end["node_id"]] for end in link["nodes"])
        toward.setdefault(one["node_id"], []).append((link["link_id"], heading(one, other)))
        toward.setdefault(other["node_id"], []).append((link["link_id"], heading(other, one)))
    networks: dict[str, list[str]] = {}
    for link in document["topology"]["links"]:
        ends = [by_id[end["node_id"]] for end in link["nodes"]]
        for end, node, other in ((link["nodes"][0], ends[0], ends[1]), (link["nodes"][1], ends[1], ends[0])):
            switching = node["node_type"] == SWITCH
            prefers = learner.prefers.get(node["name"], learner.prefers[""])
            head = None if switching else _head(held.get((node["name"], other["name"]), []), prefers,
                                                 strict=node["name"] == CUSTOMERS)
            if switching:
                text = port_label(node, end["port_number"])
            elif head:
                text = head.name if node["name"] in ADDRESS_VARIES else f"{head.name} {head.address}"
            else:
                text = bare.get((node["name"], other["name"]), "")
            if head:
                network = str(ipaddress.ip_interface(head.address).network)
                if network not in networks.setdefault(other["name"], []):
                    networks[other["name"]].append(network)
            others = [way for linked, way in toward[node["node_id"]] if linked != link["link_id"]]
            x, y, anchor = _placed_label(node, other, others, text)
            end["label"] = {"text": text, "style": (SWITCH_LABEL_STYLE if switching else LABEL_STYLE) + anchor,
                            "x": x, "y": y, "rotation": 0}
        link["link_id"] = renamed(link["link_id"], salt)
    for switch, caption in captions(document).items():
        if switch != INTERNET and networks.get(switch):
            _captioned(caption, networks[switch])
    for node in document["topology"]["nodes"]:
        node["node_id"] = renamed(node["node_id"], salt)
    for link in document["topology"]["links"]:
        for end in link["nodes"]:
            end["node_id"] = renamed(end["node_id"], salt)
    for drawing in document["topology"]["drawings"]:
        drawing["drawing_id"] = renamed(drawing["drawing_id"], salt)
    return document
