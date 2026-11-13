import json
import pathlib
import re
import uuid
from xml.etree import ElementTree

import pytest
import yaml

import topology
from range import declared, fabric
from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "deploy" / "topology"
OPENSTACK = TOPOLOGY / "range-openstack.gns3"
SYSTEM_OPENSTACK = TOPOLOGY / "system" / "range-openstack.gns3"
EVERY_MAP = [OPENSTACK, SYSTEM_OPENSTACK]
HANGUL = re.compile(r"[\uac00-\ud7a3]")
SLOT_COMPOSE = ROOT / "deploy" / "range-host" / "slot.yaml"
RFC1123 = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
ACRONYM = re.compile(r"^[A-Z]{2,5}$")
TAG = re.compile(r"\$\{CR_IMAGE_TAG(?::-([^}]*))?\}")
GNS3_2_2_TOP_LEVEL = {
    "project_id", "type", "auto_start", "auto_close", "auto_open", "revision",
    "version", "name", "scene_height", "scene_width", "zoom", "show_layers",
    "snap_to_grid", "show_grid", "grid_size", "drawing_grid_size",
    "show_interface_labels", "supplier", "variables", "topology",
}
GNS3_2_2_TOPOLOGY = {"computes", "drawings", "links", "nodes"}
SWITCH = "ethernet_switch"
def project(path):
    return json.loads(path.read_text())

def nodes(document):
    return {node["name"]: node for node in document["topology"]["nodes"]}

def wiring(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    wired: dict[str, set[str]] = {}
    for link in document["topology"]["links"]:
        ends = [by_id[end["node_id"]] for end in link["nodes"]]
        for one, other in (ends, ends[::-1]):
            if other["node_type"] == SWITCH and one["node_type"] != SWITCH:
                wired.setdefault(one["name"], set()).add(other["name"])
    return wired

def segment_ids():
    entries = yaml.safe_load(declared.DECLARATION.read_text())["segments"]
    carried = {entry["id"]: entry["id"] for entry in entries}
    for entry in entries:
        for origin in entry.get("origins") or []:
            carried[origin["id"]] = entry["id"]
    return {entry["id"] for entry in entries}, carried

def image(service):
    return TAG.sub(lambda found: found[1] or "dev", service["image"])

def openstack_expected():
    stack = declared.read()
    slot = yaml.safe_load(SLOT_COMPOSE.read_text())
    fronts = set(slot["x-wargames"]["fronts"])
    named = {}
    for role, service in stack.compose.items():
        host = stack.roles[role]
        named.setdefault(service, service if stack.hosts[host].wargames else host)
    expected = {}
    for host, entry in stack.hosts.items():
        if entry.setup:
            expected[host] = {"type": "qemu", "segments": set(entry.segments)}
        for wargame in entry.wargames:
            document = yaml.safe_load((ROOT / "wargames" / wargame / "compose.yaml").read_text())
            for service, definition in document["services"].items():
                expected[service] = {"type": "docker", "image": image(definition),
                                     "segments": {f"{wargame}-default"} | ({"estate"} if service in fronts else set())}
    for service, definition in slot["services"].items():
        expected[named[service] if definition.get("networks") else service] = {"type": "docker", "image": image(definition),
                                    "segments": set(definition.get("networks") or {})}
    for role, host in stack.roles.items():
        expected.setdefault(host, {"type": "qemu", "segments": {fabric.MANAGEMENT}})
    return stack, expected

@pytest.fixture(params=EVERY_MAP, ids=["openstack", "system-openstack"])
def any_map(request):
    return project(request.param)

def is_system(document):
    return document["project_id"] == project(SYSTEM_OPENSTACK)["project_id"]

def defended_ids():
    declared_segments, _ = segment_ids()
    return declared_segments - {fabric.MANAGEMENT}

def test_the_directory_holds_the_learner_map_and_nothing_else():
    assert sorted(TOPOLOGY.glob("*.gns3")) == [OPENSTACK]

def test_every_word_drawn_on_the_learner_map_is_korean_and_none_on_the_system_map(any_map):
    texts = [shape["text"] for shape in drawn_shapes(any_map) if shape["kind"] == "text"]
    korean = not is_system(any_map)

    kept_as_is = lambda said: IDENTIFIER.match(said) or ACRONYM.match(said)
    assert [text for text in texts if not kept_as_is(text) and bool(HANGUL.search(text)) != korean] == [], (
        "a host or network name is drawn as the machine knows it, and IDS as Korean practitioners write it too")

def test_no_two_projects_share_an_id_because_the_gns3_compute_keeps_nodes_by_id_alone():
    ids = []
    for path in EVERY_MAP:
        document = project(path)
        ids += [document["project_id"]]
        ids += [node["node_id"] for node in document["topology"]["nodes"]]
        ids += [link["link_id"] for link in document["topology"]["links"]]
        ids += [drawing["drawing_id"] for drawing in document["topology"]["drawings"]]

    assert all(str(uuid.UUID(value)) == value for value in ids)
    assert len(ids) == len(set(ids))
    assert len({project(path)["name"] for path in EVERY_MAP}) == len(EVERY_MAP)

def test_both_projects_are_revision_9_so_gns3_2_2_opens_them_and_3_upgrades_them(any_map):
    gns3 = any_map
    assert gns3["revision"] == 9
    assert gns3["type"] == "topology"
    assert set(gns3) <= GNS3_2_2_TOP_LEVEL, sorted(set(gns3) - GNS3_2_2_TOP_LEVEL)
    assert set(gns3["topology"]) == GNS3_2_2_TOPOLOGY
    assert gns3["topology"]["computes"] == []

def test_every_node_name_is_an_rfc1123_hostname_so_gns3_3_keeps_it(any_map):
    gns3 = any_map
    names = [node["name"] for node in gns3["topology"]["nodes"]]

    assert [name for name in names if not RFC1123.match(name)] == []
    assert len(names) == len(set(names))
    assert {node["compute_id"] for node in gns3["topology"]["nodes"]} == {"local"}

def test_every_link_joins_two_ports_that_exist_and_no_port_twice(any_map):
    gns3 = any_map
    by_id = {node["node_id"]: node for node in gns3["topology"]["nodes"]}
    taken = set()
    for link in gns3["topology"]["links"]:
        assert len(link["nodes"]) == 2
        for end in link["nodes"]:
            node = by_id[end["node_id"]]
            if node["node_type"] == SWITCH:
                mapping = node["properties"]["ports_mapping"]
                assert end["adapter_number"] == 0
                assert end["port_number"] in {port["port_number"] for port in mapping}
            else:
                assert 0 <= end["adapter_number"] < node["properties"]["adapters"]
                assert end["port_number"] == 0
            port = (end["node_id"], end["adapter_number"], end["port_number"])
            assert port not in taken, f"{node['name']} port {port[1:]} is linked twice"
            taken.add(port)

def test_no_qemu_node_names_a_disk_so_the_project_opens_without_images(any_map):
    gns3 = any_map
    for node in gns3["topology"]["nodes"]:
        if node["node_type"] == "qemu":
            disks = {k: v for k, v in node["properties"].items() if k.endswith("_disk_image")}
            assert set(disks.values()) <= {""}, node["name"]

def test_the_segments_are_the_declared_segments_as_switches(any_map):
    gns3 = any_map
    switches = {name for name, node in nodes(gns3).items() if node["node_type"] == SWITCH}
    if is_system(gns3):
        declared_segments = segment_ids()[0]
        assert declared_segments <= switches
        assert not {name for name in switches - declared_segments if not name.endswith("-default")}
        return
    stack = declared.read()
    for wargame in WARGAMES:
        shown = learner_of(stack, wargame)
        drawn = {name for name in switches if name not in shown.hidden}
        defended = {shown.switches[segment] for segment in defended_ids()}
        bridges = {switch for segment, switch in shown.switches.items() if segment.endswith(topology.BRIDGE_SUFFIX)}
        assert defended <= drawn and topology.MONITORING in drawn, wargame
        assert drawn - defended - {topology.MONITORING} <= bridges, wargame
        assert fabric.MANAGEMENT not in shown.switches, "no switch stands for the management segment"

def test_the_openstack_system_map_is_the_range_host_and_the_containers_of_one_slot():
    gns3 = project(SYSTEM_OPENSTACK)
    stack, expected = openstack_expected()
    declared_segments, _ = segment_ids()
    bridges = {segment for want in expected.values() for segment in want["segments"]} - declared_segments
    drawn = {name: node for name, node in nodes(gns3).items() if node["node_type"] != SWITCH}

    assert set(drawn) == set(expected), (
        f"missing {sorted(set(expected) - set(drawn))}, extra {sorted(set(drawn) - set(expected))}"
    )
    assert set(nodes(gns3)) == set(drawn) | declared_segments | bridges
    wired = wiring(gns3)
    for name, want in expected.items():
        assert drawn[name]["node_type"] == want["type"], name
        assert wired.get(name, set()) == want["segments"], name
        if want["type"] == "docker":
            assert drawn[name]["properties"]["image"] == want["image"], name
    for host, entry in stack.hosts.items():
        assert wired[host] & declared_segments == set(entry.segments), host

def drawn_shapes(document):
    shapes = []
    for drawing in document["topology"]["drawings"]:
        svg = ElementTree.fromstring(drawing["svg"])
        assert len(svg) == 1 and svg[0].tag in {"rect", "text", "line"}, drawing["svg"]
        shape = svg[0]
        shapes.append({"kind": shape.tag, "x": drawing["x"], "y": drawing["y"],
                       "width": float(svg.get("width")), "height": float(svg.get("height")),
                       "text": shape.text or "", "font": shape.get("font-family")})
    return shapes

LEARNER_MAPS = [OPENSTACK]
LEARNER_IDS = ["openstack"]
WARGAMES = sorted(yaml.safe_load(declared.DECLARATION.read_text())["hosts"]["cr-waf"]["names"])
WARGAMES = [name.split(".")[0] for name in WARGAMES]
PROJECTED = [(path, wargame) for path in LEARNER_MAPS for wargame in WARGAMES]
PROJECTED_IDS = [f"{name}-{wargame}" for name in LEARNER_IDS for wargame in WARGAMES]
IDLE = "sleep 2147483647"
WARGAME_HOST_WORDS = ("wargame", "cr-", "mgmt", "anagement", "_default", "-default")

def customers_prefer(stack, wargame):
    path = ROOT / "wargames" / wargame / "traffic.yaml"
    if not path.exists():
        return ()
    weights = yaml.safe_load(path.read_text())["origins"]
    subnets = {origin.id: origin.subnet for origin in stack.origins if origin.id != stack.default_origin}
    return tuple(subnets[origin] for origin in sorted(weights, key=lambda origin: (-weights[origin], origin))
                 if origin in subnets)

def learner_of(stack, wargame):
    customers_from = stack.roles["attacker"] if "edge" in stack.roles else ""
    return topology.learner(stack, wargame, customers_from, customers_prefer(stack, wargame))

def projected(path, wargame):
    stack = declared.read()
    return topology.for_wargame(project(path), learner_of(stack, wargame)), learner_of(stack, wargame), stack

def log_store():
    service = composed.services()["elasticsearch"]
    return service["container_name"], image(service)

def ends(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    return {frozenset((by_id[end["node_id"]]["name"], end["adapter_number"], end["port_number"])
                      for end in link["nodes"]) for link in document["topology"]["links"]}

def log_sources(stack):
    senders = {stack.roles["gateway"]} | {stack.roles[role] for role in stack.watches}
    return senders

def monitoring_ends(document):
    by_id = {node["node_id"]: node["name"] for node in document["topology"]["nodes"]}
    found = set()
    for link in document["topology"]["links"]:
        named = {by_id[end["node_id"]] for end in link["nodes"]}
        if topology.MONITORING in named:
            found |= named - {topology.MONITORING}
    return found

def host_links(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    found = set()
    for link in document["topology"]["links"]:
        one, other = (by_id[end["node_id"]] for end in link["nodes"])
        if one["node_type"] == SWITCH:
            one, other = other, one
        if other["name"] != topology.MONITORING:
            found.add((one["name"], other["name"]))
    return found

@pytest.mark.parametrize("drawn_in, wargame", PROJECTED, ids=PROJECTED_IDS)
def test_the_learner_map_is_the_declared_range_named_by_role_and_wired_as_the_system_map_wires_it(drawn_in, wargame):
    learner, shown, stack = projected(drawn_in, wargame)
    system = project(SYSTEM_OPENSTACK)
    domain = topology.domains(stack)[wargame]
    database = f"{wargame}{topology.DATABASE_SUFFIX}"
    expected = {topology.ATTACKER, topology.WAF, topology.LOG_SERVER, topology.INTERNET, topology.SERVICE,
                topology.MONITORING, domain, database}
    expected |= {topology.FIREWALL} if "edge" in stack.roles else set()
    expected |= {topology.CUSTOMERS} if customers_prefer(stack, wargame) else set()
    expected |= {topology.DATABASE_SWITCH} if f"{wargame}{topology.BRIDGE_SUFFIX}" in nodes(system) else set()
    real = {(shown_as, shown.switches[segment]) for host, segments in wiring(system).items()
            for shown_as in shown.hosts.get(host, ()) for segment in segments if segment in shown.switches}

    assert set(nodes(learner)) == expected, sorted(set(nodes(learner)) ^ expected)
    assert host_links(learner) - {(topology.CUSTOMERS, topology.INTERNET)} == real - {(topology.CUSTOMERS, topology.INTERNET)}
    assert topology.CUSTOMERS not in nodes(learner) or (topology.CUSTOMERS, topology.INTERNET) in host_links(learner), (
        "customers stand on the Internet whichever box sends them")
    assert stack.roles["scorer"] not in shown.hosts and fabric.MANAGEMENT not in shown.switches

@pytest.mark.parametrize("drawn_in, wargame", PROJECTED, ids=PROJECTED_IDS)
def test_a_wargame_s_map_shows_its_own_site_and_database_and_no_other_wargame_s(drawn_in, wargame):
    learner, _, stack = projected(drawn_in, wargame)
    others = {name for other, domain in topology.domains(stack).items() if other != wargame
              for name in (domain, f"{other}{topology.DATABASE_SUFFIX}")}

    assert topology.domains(stack)[wargame] in nodes(learner)
    assert not others & set(nodes(learner))
    assert not [shape for shape in drawn_shapes(learner) if any(other in shape["text"] for other in others)]

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_no_word_on_a_learner_map_names_the_platform_its_management_segment_or_a_machine_s_own_name(drawn_in):
    document = project(drawn_in)
    said = [shape["text"] for shape in drawn_shapes(document) if shape["kind"] == "text"]
    scorer = declared.read().roles["scorer"]
    named = [node["name"] for node in document["topology"]["nodes"]] + [document["name"]]

    assert [text for text in said if scorer in text or "mgmt" in text or "anagement" in text] == []
    assert [text for text in said + named if any(word in text for word in WARGAME_HOST_WORDS)] == []
    assert "cr-" not in json.dumps(document)

@pytest.mark.parametrize("drawn_in, wargame", PROJECTED, ids=PROJECTED_IDS)
def test_the_log_server_sits_on_the_monitoring_switch_with_exactly_the_hosts_whose_records_reach_it(drawn_in, wargame):
    learner, shown, stack = projected(drawn_in, wargame)
    sources = {shown.shown(host) for host in log_sources(stack)}

    assert shown.hosts[log_store()[0]] == (topology.LOG_SERVER,)
    assert wiring(learner)[topology.LOG_SERVER] == {topology.MONITORING}
    assert monitoring_ends(learner) == sources | {topology.LOG_SERVER}
    assert not {topology.ATTACKER, topology.CUSTOMERS} & monitoring_ends(learner)
    assert sources == {topology.WAF, topology.FIREWALL, topology.domains(stack)[wargame]}, (
        "the WAF's and the edge's logs and the estate sensor on the sites' host reach the store")

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_every_host_on_a_learner_map_is_a_display_container_of_one_pinned_image_that_only_idles(drawn_in):
    hosts = [node for node in project(drawn_in)["topology"]["nodes"] if node["node_type"] != SWITCH]

    assert hosts and {node["node_type"] for node in hosts} == {"docker"}
    assert {node["properties"]["image"] for node in hosts} == {topology.DISPLAY_IMAGE}
    assert re.fullmatch(r"busybox@sha256:[0-9a-f]{64}", topology.DISPLAY_IMAGE), "pinned by digest"
    assert {node["properties"]["start_command"] for node in hosts} == {IDLE}
    assert {node["console_type"] for node in hosts} == {"none"}
    assert all(node["properties"]["adapters"] == sum(end["node_id"] == node["node_id"] for link in
                                                       project(drawn_in)["topology"]["links"] for end in link["nodes"])
               for node in hosts), "a display node has one adapter per link and no more"

def dashed_ends(document):
    ends = []
    for drawing in document["topology"]["drawings"]:
        line = ElementTree.fromstring(drawing["svg"])[0]
        if line.tag == "line" and line.get("stroke-dasharray"):
            ends.append([(drawing["x"] + float(line.get(f"x{at}")), drawing["y"] + float(line.get(f"y{at}"))) for at in (1, 2)])
    return ends

@pytest.mark.parametrize("drawn_in, wargame", PROJECTED, ids=PROJECTED_IDS)
def test_each_ids_is_its_own_sensor_fed_by_a_dashed_mirror_line_from_the_host_it_watches(drawn_in, wargame):
    learner, shown, _ = projected(drawn_in, wargame)
    centre = {name: (node["x"] + 30, node["y"] + 30) for name, node in nodes(learner).items()}
    boxes = [shape for shape in drawn_shapes(learner) if shape["kind"] == "rect" and shape["width"] < 100]
    marks = [shape for shape in drawn_shapes(learner) if shape["kind"] == "text" and shape["text"] == "IDS"]
    inside = lambda mark, box: box["x"] <= mark["x"] <= box["x"] + box["width"] and box["y"] <= mark["y"] <= box["y"] + box["height"]
    distance = lambda point, name: (centre[name][0] - point[0]) ** 2 + (centre[name][1] - point[1]) ** 2
    watched = [min(centre, key=lambda name: min(distance(end, name) for end in line)) for line in dashed_ends(learner)]

    assert len(marks) == len(boxes) == len(dashed_ends(learner)) and all(any(inside(mark, box) for box in boxes) for mark in marks)
    assert sorted(watched) == sorted(set(shown.sensors.values())), (
        "sensor in Kibana names these hosts, so the map shows whose traffic each IDS is fed")
    assert not [switch for switch, caption in topology.captions(learner).items() if ">IDS<" in caption["svg"]]

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_zones_are_the_internet_the_dmz_the_db_zone_and_the_management_network(drawn_in):
    captions = sorted(ElementTree.fromstring(caption["svg"])[0].text for caption in topology.captions(project(drawn_in)).values())

    assert captions == ["DB존", "DMZ", "관리망", "인터넷"]
