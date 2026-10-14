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
DOCKER = TOPOLOGY / "range-docker.gns3"
OPENSTACK = TOPOLOGY / "range-openstack.gns3"
DOCKER_KO = TOPOLOGY / "range-docker.ko.gns3"
OPENSTACK_KO = TOPOLOGY / "range-openstack.ko.gns3"
SYSTEM_DOCKER = TOPOLOGY / "system" / "range-docker.gns3"
SYSTEM_OPENSTACK = TOPOLOGY / "system" / "range-openstack.gns3"
PAIRS = {DOCKER: DOCKER_KO, OPENSTACK: OPENSTACK_KO}
SYSTEMS = {DOCKER: SYSTEM_DOCKER, DOCKER_KO: SYSTEM_DOCKER, OPENSTACK: SYSTEM_OPENSTACK,
           OPENSTACK_KO: SYSTEM_OPENSTACK}
FLAVORS = {DOCKER: "", DOCKER_KO: "", OPENSTACK: "openstack", OPENSTACK_KO: "openstack"}
EVERY_MAP = [*PAIRS, *PAIRS.values(), SYSTEM_DOCKER, SYSTEM_OPENSTACK]
BUNDLED_SYMBOL = re.compile(r"^:/symbols/affinity/(square|circle)/(blue|gray|green|red)/[a-z0-9_]+\.svg$")
DOCKERFILE = ROOT / "deploy" / "gns3" / "Dockerfile"
KOREAN_NAME = re.compile(r" \([\uac00-\ud7a3]+\)")
HANGUL = re.compile(r"[\uac00-\ud7a3]")
SENSOR_COMPOSE = ROOT / "deploy" / "wargame-host" / "sensor.yaml"
RFC1123 = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
TAG = re.compile(r"\$\{FSL_IMAGE_TAG(?::-([^}]*))?\}")
GNS3_2_2_TOP_LEVEL = {
    "project_id", "type", "auto_start", "auto_close", "auto_open", "revision",
    "version", "name", "scene_height", "scene_width", "zoom", "show_layers",
    "snap_to_grid", "show_grid", "grid_size", "drawing_grid_size",
    "show_interface_labels", "supplier", "variables", "topology",
}
GNS3_2_2_TOPOLOGY = {"computes", "drawings", "links", "nodes"}
SWITCH = "ethernet_switch"
MONITORING = "monitoring"
STRAIGHT_WITHIN = 6
UBUNTU_SIZE = (65, 59)

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

def network_keys(service):
    attached = service.get("networks") or []
    return list(attached) if isinstance(attached, (list, dict)) else []

def docker_expected():
    base = declared.read()
    _, carried = segment_ids()
    labelled = {
        key: carried[(entry or {}).get("labels", {})["fsl.segment.id"]]
        for key, entry in composed.networks().items()
    }
    services = composed.services()
    named = {base.compose[role]: host for role, host in base.roles.items() if role in base.compose}
    created_by_the_session = {
        labelled[key] for key, entry in (yaml.safe_load(composed.SESSION.read_text())["networks"]).items()
        if not (entry or {}).get("external")
    }
    expected = {}
    for service, entry in services.items():
        name = named.get(service) or entry.get("container_name") or f"fsl-{service}"
        segments = {labelled[key] for key in network_keys(entry)}
        if name == base.roles["scorer"]:
            segments |= created_by_the_session
        expected[name] = {"image": image(entry), "segments": segments}
    return expected

def openstack_expected():
    stack = declared.read(flavor="openstack")
    expected = {}
    for host, entry in stack.hosts.items():
        bridges = {f"{wargame}-default" for wargame in entry.wargames}
        expected[host] = {"type": "qemu", "segments": set(entry.segments) | bridges}
        served = set()
        for wargame in entry.wargames:
            document = yaml.safe_load((ROOT / "wargames" / wargame / "compose.yaml").read_text())
            for service, definition in document["services"].items():
                served.add(service)
                expected[service] = {"type": "docker", "image": image(definition),
                                     "segments": {f"{wargame}-default"}}
        sensors = yaml.safe_load(SENSOR_COMPOSE.read_text())["services"]
        for role, service in stack.compose.items():
            if entry.wargames and stack.roles.get(role) == host and service not in served:
                expected[service] = {"type": "docker", "image": image(sensors[service]),
                                     "segments": set()}
    for role, host in stack.roles.items():
        expected.setdefault(host, {"type": "qemu", "segments": {fabric.MANAGEMENT}})
    return stack, expected

def korean_id(english_id):
    return str(uuid.uuid5(uuid.UUID(english_id), "ko"))

def english_of(document):
    for system in (SYSTEM_DOCKER, SYSTEM_OPENSTACK):
        if document["project_id"] == project(system)["project_id"]:
            return document
    for english in PAIRS:
        kept = project(english)
        if document["project_id"] in (kept["project_id"], korean_id(kept["project_id"])):
            return kept
    raise AssertionError(f"{document['name']} pairs with no English project")

@pytest.fixture(params=[DOCKER, DOCKER_KO, OPENSTACK, OPENSTACK_KO],
                ids=["docker", "docker-ko", "openstack", "openstack-ko"])
def gns3(request):
    return project(request.param)

@pytest.fixture(params=EVERY_MAP, ids=["docker", "openstack", "docker-ko", "openstack-ko",
                                       "system-docker", "system-openstack"])
def any_map(request):
    return project(request.param)

def is_system(document):
    return document["project_id"] in {project(path)["project_id"] for path in (SYSTEM_DOCKER, SYSTEM_OPENSTACK)}

def defended_ids():
    declared_segments, _ = segment_ids()
    return declared_segments - {fabric.MANAGEMENT}

def test_the_directory_holds_each_english_project_and_its_korean_pair_and_nothing_else():
    assert sorted(TOPOLOGY.glob("*.gns3")) == sorted([*PAIRS, *PAIRS.values()])

def without_words(svg):
    drawn = ElementTree.fromstring(svg)
    if drawn[0].tag == "text":
        drawn.attrib.pop("width")
        drawn[0].text = ""
    return ElementTree.tostring(drawn, encoding="unicode")

@pytest.mark.parametrize("english", list(PAIRS), ids=["docker", "openstack"])
def test_a_korean_project_is_its_english_pair_with_its_own_ids_and_only_the_drawn_words_changed(english):
    kept, korean = project(english), project(PAIRS[english])
    expected = json.loads(json.dumps(kept))
    expected["project_id"] = korean_id(kept["project_id"])
    assert korean["name"].startswith(kept["name"])
    assert KOREAN_NAME.fullmatch(korean["name"].removeprefix(kept["name"])), korean["name"]
    expected["name"] = korean["name"]
    for node in expected["topology"]["nodes"]:
        node["node_id"] = korean_id(node["node_id"])
    for link in expected["topology"]["links"]:
        link["link_id"] = korean_id(link["link_id"])
        for end in link["nodes"]:
            end["node_id"] = korean_id(end["node_id"])
    drawings = korean["topology"]["drawings"]
    assert len(drawings) == len(expected["topology"]["drawings"])
    for drawing, said in zip(expected["topology"]["drawings"], drawings):
        drawing["drawing_id"] = korean_id(drawing["drawing_id"])
        assert without_words(drawing["svg"]) == without_words(said["svg"]), said["svg"]
        drawing["svg"] = said["svg"]

    assert korean == expected

def test_every_word_drawn_on_a_korean_map_is_korean_and_none_on_an_english_one(any_map):
    gns3 = any_map
    texts = [shape["text"] for shape in drawn_shapes(gns3) if shape["kind"] == "text"]
    english = [shape["text"] for shape in drawn_shapes(english_of(gns3)) if shape["kind"] == "text"]
    korean = gns3["project_id"] != english_of(gns3)["project_id"]

    assert [text for text, said in zip(texts, english)
            if not IDENTIFIER.match(said) and bool(HANGUL.search(text)) != korean] == []
    assert [text for text, said in zip(texts, english) if IDENTIFIER.match(said) and text != said] == [], (
        "a host or network name is drawn as the machine knows it, in either language")

def test_no_two_projects_share_an_id_because_the_gns3_compute_keeps_nodes_by_id_alone():
    ids = []
    for path in EVERY_MAP:
        document = project(path)
        ids += [document["project_id"]]
        ids += [node["node_id"] for node in document["topology"]["nodes"]]
        ids += [link["link_id"] for link in document["topology"]["links"]]
        ids += [drawing["drawing_id"] for drawing in document["topology"]["drawings"]]

    assert len(ids) == len(set(ids))
    assert len({project(path)["name"] for path in EVERY_MAP}) == 6

def test_both_projects_are_revision_9_so_gns3_2_2_opens_them_and_3_upgrades_them(any_map):
    gns3 = any_map
    assert gns3["revision"] == 9
    assert gns3["type"] == "topology"
    assert set(gns3) <= GNS3_2_2_TOP_LEVEL, sorted(set(gns3) - GNS3_2_2_TOP_LEVEL)
    assert set(gns3["topology"]) == GNS3_2_2_TOPOLOGY
    assert gns3["topology"]["computes"] == []

def test_every_id_in_a_project_is_a_uuid_and_unique(any_map):
    gns3 = any_map
    ids = [gns3["project_id"]]
    ids += [node["node_id"] for node in gns3["topology"]["nodes"]]
    ids += [link["link_id"] for link in gns3["topology"]["links"]]
    ids += [drawing["drawing_id"] for drawing in gns3["topology"]["drawings"]]

    assert all(str(uuid.UUID(value)) == value for value in ids)
    assert len(ids) == len(set(ids))

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
    declared_segments = segment_ids()[0] if is_system(gns3) else defended_ids()
    switches = {name for name, node in nodes(gns3).items() if node["node_type"] == SWITCH}

    allowed = set() if is_system(gns3) else {MONITORING}

    assert declared_segments <= switches
    assert not {name for name in switches - declared_segments - allowed if not name.endswith("-default")}
    assert is_system(gns3) or (fabric.MANAGEMENT not in switches and MONITORING in switches)

def test_the_docker_system_map_is_the_compose_stack_one_container_per_service():
    gns3 = project(SYSTEM_DOCKER)
    expected = docker_expected()
    declared_segments, _ = segment_ids()
    drawn = {name: node for name, node in nodes(gns3).items() if node["node_type"] != SWITCH}

    assert set(drawn) == set(expected), (
        f"missing {sorted(set(expected) - set(drawn))}, extra {sorted(set(drawn) - set(expected))}"
    )
    assert set(nodes(gns3)) == set(drawn) | declared_segments
    wired = wiring(gns3)
    for name, want in expected.items():
        assert drawn[name]["node_type"] == "docker"
        assert drawn[name]["properties"]["image"] == want["image"], name
        assert wired.get(name, set()) == want["segments"], name
        assert drawn[name]["properties"]["adapters"] == len(want["segments"]), name

def test_every_host_a_docker_role_names_is_a_node_of_the_docker_system_map():
    drawn = nodes(project(SYSTEM_DOCKER))

    assert set(declared.read().roles.values()) <= set(drawn)

def test_the_openstack_system_map_is_the_declared_hosts_and_the_wargame_hosts_containers():
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

def test_the_edge_is_a_vm_with_three_nics_in_the_order_opnsense_assigns_them():
    gns3 = project(SYSTEM_OPENSTACK)
    edge = nodes(gns3)[declared.read(flavor="openstack").roles["edge"]]
    by_id = {node["node_id"]: node["name"] for node in gns3["topology"]["nodes"]}
    order = {}
    for link in gns3["topology"]["links"]:
        ends = {end["node_id"]: end for end in link["nodes"]}
        if edge["node_id"] in ends:
            other, = [by_id[node_id] for node_id in ends if node_id != edge["node_id"]]
            order[ends[edge["node_id"]]["adapter_number"]] = other

    assert edge["node_type"] == "qemu"
    assert edge["properties"]["adapters"] == 3
    assert [order[n] for n in sorted(order)] == list(
        declared.read(flavor="openstack").hosts["fsl-edge"].segments
    )

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

def inside(x, y, box):
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]

def test_every_drawing_is_one_shape_both_gns3_releases_draw_in_a_font_the_web_ui_has(any_map):
    gns3 = any_map
    texts = [shape for shape in drawn_shapes(gns3) if shape["kind"] == "text"]

    assert texts
    assert {shape["font"] for shape in texts} == {"Noto Sans"}

def test_each_declared_segment_is_a_titled_zone_holding_its_switch(any_map):
    gns3 = any_map
    entries = [entry for entry in yaml.safe_load(declared.DECLARATION.read_text())["segments"]
               if is_system(gns3) or entry["id"] in defended_ids()]
    shapes = drawn_shapes(gns3)
    english = [shape["text"] for shape in drawn_shapes(english_of(gns3))]
    zones = [shape for shape in shapes if shape["kind"] == "rect"]
    switches = nodes(gns3)
    for entry in entries:
        titles = [shape for shape, said in zip(shapes, english)
                  if shape["kind"] == "text" and said.startswith(entry["name"])]
        assert len(titles) == 1, entry["name"]
        holding = [zone for zone in zones if inside(titles[0]["x"], titles[0]["y"], zone)
                   and inside(switches[entry["id"]]["x"] + 25, switches[entry["id"]]["y"] + 25, zone)]
        assert holding, f"{entry['name']}: no zone holds both its title and the {entry['id']} switch"

@pytest.fixture(params=[SYSTEM_DOCKER, SYSTEM_OPENSTACK], ids=["system-docker", "system-openstack"])
def system_map(request):
    return project(request.param)

def test_a_node_with_no_nic_says_whose_network_it_watches_next_to_it(system_map):
    gns3 = system_map
    linked = {end["node_id"] for link in gns3["topology"]["links"] for end in link["nodes"]}
    names = set(nodes(gns3))
    english = [shape["text"] for shape in drawn_shapes(english_of(gns3))]
    texts = [dict(shape, text=said) for shape, said in zip(drawn_shapes(gns3), english) if shape["kind"] == "text"]
    unlinked = [node for node in gns3["topology"]["nodes"] if node["node_id"] not in linked]

    assert unlinked
    for node in unlinked:
        near = [shape["text"] for shape in texts
                if abs(shape["x"] - node["x"]) < 250 and abs(shape["y"] - node["y"]) < 150]
        assert [said for said in near if "host network" in said or any(
            name in said for name in names - {node["name"]})], (node["name"], near)

LEARNER_MAPS = [DOCKER, DOCKER_KO, OPENSTACK, OPENSTACK_KO]
LEARNER_IDS = ["docker", "docker-ko", "openstack", "openstack-ko"]

def log_store():
    service = composed.services()["elasticsearch"]
    return service["container_name"], image(service)

def ends(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    return {frozenset((by_id[end["node_id"]]["name"], end["adapter_number"], end["port_number"])
                      for end in link["nodes"]) for link in document["topology"]["links"]}

def sensor_node(stack, drawn, role):
    return stack.compose.get(role) if stack.compose.get(role) in drawn else stack.roles[role]

def network_mode(stack, flavor, role):
    services = yaml.safe_load(SENSOR_COMPOSE.read_text())["services"] if flavor else composed.services()
    return (services.get(stack.compose.get(role, "")) or {}).get("network_mode", "")

def nic_owner(stack, flavor, role):
    mode = network_mode(stack, flavor, role)
    if mode.startswith("service:"):
        shared = mode.removeprefix("service:")
        return next(stack.roles[other] for other, service in stack.compose.items() if service == shared)
    return stack.roles[role]

def own_nic(system, name):
    return name in nodes(system) and nodes(system)[name]["properties"].get("adapters", 0) > 0

def log_shippers(stack, flavor):
    if flavor:
        senders = {stack.roles["gateway"]} | {stack.roles[role] for role in stack.watches}
        return senders | {host for host, entry in stack.hosts.items() if entry.logs}
    services = yaml.safe_load(composed.SESSION.read_text())["services"]
    written = {volume.split(":")[0] for role in ("gateway", *stack.watches)
               for volume in services[stack.compose[role]].get("volumes") or []}
    return {f"fsl-{name}" for name, service in services.items()
            if fabric.MANAGEMENT in network_keys(service) and name not in stack.compose.values()
            and written & {volume.split(":")[0] for volume in service.get("volumes") or []}}

def mgmt_adapters(system, names):
    by_id = {node["node_id"]: node["name"] for node in system["topology"]["nodes"]}
    adapters = {}
    for link in system["topology"]["links"]:
        named = {by_id[end["node_id"]]: end["adapter_number"] for end in link["nodes"]}
        if fabric.MANAGEMENT in named:
            adapters.update({name: adapter for name, adapter in named.items() if name in names})
    return adapters

def monitoring_ends(document):
    by_id = {node["node_id"]: node["name"] for node in document["topology"]["nodes"]}
    found = {}
    for link in document["topology"]["links"]:
        named = {by_id[end["node_id"]]: end["adapter_number"] for end in link["nodes"]}
        if MONITORING in named:
            found.update({name: adapter for name, adapter in named.items() if name != MONITORING})
    return found

def learner_expected(system, stack, flavor=""):
    defended = {name for name, node in nodes(system).items() if node["node_type"] == SWITCH} - {fabric.MANAGEMENT}
    drawn = nodes(system)
    plumbing = {stack.roles["scorer"]} | ({stack.roles["proxy"]} - {stack.roles["attacker"]})
    sensing = {sensor_node(stack, drawn, role) for role in stack.watches}
    sensing = {name for name in sensing if own_nic(system, name)}
    kept = {name for name, on in wiring(system).items() if on & defended} - plumbing
    return kept | sensing | log_shippers(stack, flavor) | {log_store()[0]}, defended

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_learner_map_is_the_system_map_without_the_management_segment_and_the_training_plumbing(drawn_in):
    learner, system = project(drawn_in), project(SYSTEMS[drawn_in])
    stack = declared.read(flavor=FLAVORS[drawn_in])
    hosts, defended = learner_expected(system, stack, FLAVORS[drawn_in])
    called = topology.shown_as(stack)
    switches = {name for name, node in nodes(learner).items() if node["node_type"] == SWITCH}
    shown = set(nodes(learner)) - switches
    kept = hosts | defended
    wired = {link for link in ends(learner) if MONITORING not in {end[0] for end in link}}
    hosts = {called.get(name, name) for name in hosts}

    assert switches == defended | {MONITORING}
    assert shown == hosts, f"missing {sorted(hosts - shown)}, extra {sorted(shown - hosts)}"
    assert wired == {frozenset((called.get(name, name), adapter, port) for name, adapter, port in link)
                     for link in ends(system) if {end[0] for end in link} <= kept}
    named_in_system = {called.get(name, name): name for name in nodes(system)}
    for name, node in nodes(learner).items():
        if name in named_in_system:
            assert node["node_type"] == nodes(system)[named_in_system[name]]["node_type"], name
            assert node["properties"] == nodes(system)[named_in_system[name]]["properties"], name
    assert stack.roles["scorer"] not in nodes(learner) and fabric.MANAGEMENT not in nodes(learner)

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_no_word_on_a_learner_map_names_the_platform_or_its_management_segment(drawn_in):
    english = [shape["text"] for shape in drawn_shapes(english_of(project(drawn_in))) if shape["kind"] == "text"]
    scorer = declared.read(flavor=FLAVORS[drawn_in]).roles["scorer"]

    assert [said for said in english if scorer in said or "mgmt" in said or "anagement" in said] == []

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_log_store_sits_on_the_monitoring_segment_with_exactly_the_hosts_that_ship_records_to_it(drawn_in):
    learner, system = project(drawn_in), project(SYSTEMS[drawn_in])
    flavor = FLAVORS[drawn_in]
    stack = declared.read(flavor=flavor)
    name, wanted = log_store()
    store = nodes(learner)[name]
    shippers = log_shippers(stack, flavor)
    adapters = mgmt_adapters(system, shippers | {name})

    assert store["node_type"] == "docker" and store["properties"]["image"] == wanted
    assert wiring(learner)[name] == {MONITORING}
    assert monitoring_ends(learner) == {**{shipper: adapters[shipper] for shipper in shippers}, name: adapters.get(name, 0)}
    assert not {stack.roles["attacker"], stack.roles["scorer"]} & set(monitoring_ends(learner))
    assert flavor != "openstack" or shippers == {stack.roles["gateway"], stack.roles["edge"], stack.roles["wargames"]}
    assert flavor == "openstack" or shippers == {"fsl-filebeat"}
    assert store["label"]["text"] == name

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_monitoring_is_a_titled_zone_holding_its_switch_and_the_log_store(drawn_in):
    learner = project(drawn_in)
    shapes = drawn_shapes(learner)
    english = [shape["text"] for shape in drawn_shapes(english_of(learner))]
    zones = [shape for shape in shapes if shape["kind"] == "rect"]
    titles = [shape for shape, said in zip(shapes, english) if shape["kind"] == "text" and said == "Monitoring"]

    assert len(titles) == 1
    for name in (MONITORING, log_store()[0]):
        node = nodes(learner)[name]
        assert [zone for zone in zones if inside(titles[0]["x"], titles[0]["y"], zone)
                and inside(node["x"] + 30, node["y"] + 30, zone)], name

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_no_node_on_a_learner_map_floats(drawn_in):
    learner = project(drawn_in)
    linked = {end["node_id"] for link in learner["topology"]["links"] for end in link["nodes"]}

    assert [node["name"] for node in learner["topology"]["nodes"] if node["node_id"] not in linked] == []

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_a_sensor_with_no_nic_of_its_own_is_folded_into_the_node_whose_nic_it_uses(drawn_in):
    learner, system = project(drawn_in), project(SYSTEMS[drawn_in])
    flavor = FLAVORS[drawn_in]
    stack = declared.read(flavor=flavor)
    folded = [role for role in stack.watches if sensor_node(stack, nodes(system), role) not in nodes(learner)]

    assert folded, "every learner map folds at least one host-network sensor into its host"
    for role in folded:
        assert not own_nic(system, sensor_node(stack, nodes(system), role)), role
        owner = nic_owner(stack, flavor, role)
        assert owner in nodes(learner) and nodes(learner)[owner]["label"]["text"] == owner, (role, owner)

def centre(node):
    width, height = UBUNTU_SIZE if node["symbol"] == "ubuntu.svg" else (60, 60)
    return node["x"] + width / 2, node["y"] + height / 2

def stretches(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    return [(tuple(by_id[end["node_id"]]["name"] for end in link["nodes"]),
             tuple(centre(by_id[end["node_id"]]) for end in link["nodes"])) for link in document["topology"]["links"]]

def turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

def crossing(one, other):
    (a, b), (c, d) = one, other
    return turn(a, b, c) * turn(a, b, d) < 0 and turn(c, d, a) * turn(c, d, b) < 0

def overlapping(one, other, shared):
    (a, b), (c, d) = one, other
    away = lambda start, end: (end[0] - start[0], end[1] - start[1])
    first, second = (away(a, b) if a == shared else away(b, a)), (away(c, d) if c == shared else away(d, c))
    return turn((0, 0), first, second) == 0 and first[0] * second[0] + first[1] * second[1] > 0

def clearance(point, line):
    (ax, ay), (bx, by) = line
    length = (bx - ax) ** 2 + (by - ay) ** 2
    along = max(0, min(1, ((point[0] - ax) * (bx - ax) + (point[1] - ay) * (by - ay)) / length))
    return ((ax + along * (bx - ax) - point[0]) ** 2 + (ay + along * (by - ay) - point[1]) ** 2) ** 0.5

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_every_learner_link_is_one_straight_line_level_upright_or_a_single_diagonal(drawn_in):
    learner = project(drawn_in)
    diagonal = [names for names, ((ax, ay), (bx, by)) in stretches(learner)
                if abs(ax - bx) > STRAIGHT_WITHIN and abs(ay - by) > STRAIGHT_WITHIN]

    assert [link for link in learner["topology"]["links"] if (link.get("link_style") or {}).get("link_type")] == []
    assert len(diagonal) <= len(learner["topology"]["links"]) // 2, diagonal

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_no_two_learner_links_cross_or_share_a_stretch_of_line_and_none_runs_through_a_node(drawn_in):
    learner = project(drawn_in)
    drawn = stretches(learner)
    centres = {node["name"]: centre(node) for node in learner["topology"]["nodes"]}
    for at, (names, line) in enumerate(drawn):
        for other_names, other in drawn[at + 1:]:
            shared = set(names) & set(other_names)
            if shared:
                assert not overlapping(line, other, centres[shared.pop()]), (names, other_names)
            else:
                assert not crossing(line, other), (names, other_names)
        for name, point in centres.items():
            if name not in names:
                assert clearance(point, line) > topology.SYMBOL_SIZE, (names, name)

def domains():
    named = declared.read().hosts[declared.read().roles["gateway"]].names
    return {name.split(".")[0]: name for name in named}

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_waf_and_each_site_show_the_domain_learners_type(drawn_in):
    learner = project(drawn_in)
    stack = declared.read(flavor=FLAVORS[drawn_in])
    called = topology.shown_as(stack)
    services = topology.addressing(learner, stack, [])["services"]

    assert set(domains().values()) == {"board.com", "corp.com"} == set(topology.domains(stack).values())
    for role, domain in domains().items():
        site = stack.compose[role] if stack.compose[role] in called else stack.roles[role]
        assert called[site] == domain and nodes(learner)[domain]["label"]["text"] == domain, (site, domain)
        assert {"name": domain, "host": stack.roles["gateway"], "port": topology.SITE_PORT} in services

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_a_learner_map_draws_no_title_no_legend_and_no_note_only_a_caption_for_each_zone(drawn_in):
    learner = project(drawn_in)
    stack = declared.read(flavor=FLAVORS[drawn_in])
    shapes = drawn_shapes(learner)
    english = [shape["text"] for shape in drawn_shapes(english_of(learner)) if shape["kind"] == "text"]
    zones = [shape for shape in shapes if shape["kind"] == "rect"]
    texts = [shape for shape in shapes if shape["kind"] == "text"]
    switches = {name for name, node in nodes(learner).items() if node["node_type"] == SWITCH}
    segment_names = {entry["name"] for entry in yaml.safe_load(declared.DECLARATION.read_text())["segments"]
                     if entry["id"] in defended_ids()} | {"Monitoring"}
    networks = {name.replace("-", "_") for name in switches if name.endswith("-default")}
    hosts = {host for host, entry in stack.hosts.items() if entry.wargames}

    assert len(texts) == len(zones)
    for text in texts:
        holding = [zone for zone in zones if inside(text["x"], text["y"], zone)]
        assert holding, text["text"]
        smallest = min(holding, key=lambda zone: zone["width"] * zone["height"])
        assert [other for other in texts if other is not text and inside(other["x"], other["y"], smallest)
                and min((zone for zone in zones if inside(other["x"], other["y"], zone)),
                        key=lambda zone: zone["width"] * zone["height"]) is smallest] == []
    assert set(english) <= segment_names | networks | hosts, sorted(set(english) - segment_names - networks - hosts)
    assert set(topology.captions(learner)) == switches

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_every_symbol_is_one_gns3_bundles_or_one_the_gns3_image_fetches(drawn_in):
    dockerfile = DOCKERFILE.read_text()
    fetched = re.search(r"for name in ([^;]+); do", dockerfile)[1].split()
    assert "GNS3/gns3-registry/${REGISTRY}/symbols/${name}" in dockerfile
    for node in project(drawn_in)["topology"]["nodes"]:
        symbol = node["symbol"]
        assert BUNDLED_SYMBOL.match(symbol) or (
            symbol in fetched and symbol.removesuffix(".svg") + ".txt" in fetched), (node["name"], symbol)

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_a_symbol_tells_a_vm_from_a_container_and_the_defence_from_the_sites(drawn_in):
    learner = project(drawn_in)
    stack = declared.read(flavor=FLAVORS[drawn_in])
    shown = nodes(learner)

    called = topology.shown_as(stack)

    def symbol(role):
        service, host = stack.compose.get(role, ""), stack.roles[role]
        name = called.get(service, service) if called.get(service, service) in shown else called.get(host, host)
        return shown[name]["symbol"]

    system = nodes(project(SYSTEMS[drawn_in]))
    drawn_sensors = [role for role in stack.watches if sensor_node(stack, system, role) in shown]

    for node in shown.values():
        if node["node_type"] == "docker":
            assert "/circle/" in node["symbol"], node["name"]
        if node["node_type"] == "qemu":
            assert "/square/" in node["symbol"] or not node["symbol"].startswith(":"), node["name"]
    assert symbol("attacker").endswith("/red/scull.svg")
    assert symbol("gateway").endswith("/green/shield.svg")
    assert {shown[sensor_node(stack, system, role)]["symbol"].rsplit("/", 1)[1]
            for role in drawn_sensors} <= {"inspect.svg", "firewall.svg"}
    assert "edge" not in stack.roles or symbol("edge").endswith("/green/firewall.svg")
    assert symbol("board").endswith("/blue/server.svg") and symbol("board-db").endswith("/blue/storage.svg")
    assert shown[log_store()[0]]["symbol"].endswith("/gray/statistics.svg")
