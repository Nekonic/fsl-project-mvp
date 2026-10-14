import json
import pathlib
import re
import uuid
from xml.etree import ElementTree

import pytest
import yaml

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
RFC1123 = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TAG = re.compile(r"\$\{FSL_IMAGE_TAG(?::-([^}]*))?\}")
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
    korean = gns3["project_id"] != english_of(gns3)["project_id"]

    assert [text for text in texts if bool(HANGUL.search(text)) != korean] == []

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

    assert declared_segments <= switches
    assert not {name for name in switches - declared_segments if not name.endswith("-default")}
    assert is_system(gns3) or fabric.MANAGEMENT not in switches

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

def test_a_node_with_no_nic_says_whose_network_it_watches_next_to_it(any_map):
    gns3 = any_map
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

def learner_expected(system, stack):
    defended = {name for name, node in nodes(system).items() if node["node_type"] == SWITCH} - {fabric.MANAGEMENT}
    drawn = nodes(system)
    plumbing = {stack.roles["scorer"]} | ({stack.roles["proxy"]} - {stack.roles["attacker"]})
    sensing = {stack.compose.get(role) if stack.compose.get(role) in drawn else stack.roles[role]
               for role in stack.watches}
    kept = {name for name, on in wiring(system).items() if on & defended} - plumbing
    return kept | sensing | {log_store()[0]}, defended

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_learner_map_is_the_system_map_without_the_management_segment_and_the_training_plumbing(drawn_in):
    learner, system = project(drawn_in), project(SYSTEMS[drawn_in])
    stack = declared.read(flavor=FLAVORS[drawn_in])
    hosts, defended = learner_expected(system, stack)
    switches = {name for name, node in nodes(learner).items() if node["node_type"] == SWITCH}
    shown = set(nodes(learner)) - switches
    kept = hosts | defended

    assert switches == defended
    assert shown == hosts, f"missing {sorted(hosts - shown)}, extra {sorted(shown - hosts)}"
    assert ends(learner) == {link for link in ends(system) if {end[0] for end in link} <= kept}
    for name, node in nodes(learner).items():
        if name in nodes(system):
            assert node["node_type"] == nodes(system)[name]["node_type"], name
            assert node["properties"] == nodes(system)[name]["properties"], name
    assert stack.roles["scorer"] not in nodes(learner) and fabric.MANAGEMENT not in nodes(learner)

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_no_word_on_a_learner_map_names_the_platform_or_its_management_segment(drawn_in):
    english = [shape["text"] for shape in drawn_shapes(english_of(project(drawn_in))) if shape["kind"] == "text"]
    scorer = declared.read(flavor=FLAVORS[drawn_in]).roles["scorer"]

    assert [said for said in english if scorer in said or "mgmt" in said or "anagement" in said] == []

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_log_store_is_drawn_unlinked_as_the_place_the_waf_and_the_sensors_send_records(drawn_in):
    learner = project(drawn_in)
    name, wanted = log_store()
    store = nodes(learner)[name]
    linked = {end["node_id"] for link in learner["topology"]["links"] for end in link["nodes"]}
    stack = declared.read(flavor=FLAVORS[drawn_in])
    senders = {stack.roles["gateway"]} | ({stack.compose.get(role) if stack.compose.get(role) in nodes(learner)
                                           else stack.roles[role] for role in stack.watches} - {stack.roles["gateway"]})
    english = [shape for shape in drawn_shapes(english_of(learner)) if shape["kind"] == "text"]
    beside = [shape["text"] for shape in english
              if abs(shape["x"] - store["x"]) < 120 and abs(shape["y"] - store["y"]) < 60]

    assert store["node_type"] == "docker" and store["properties"]["image"] == wanted
    assert store["node_id"] not in linked, "no cable on the learner map carries the records"
    assert [said for said in beside if "log store" in said and all(sender in said for sender in senders)], beside

def domains():
    named = declared.read().hosts[declared.read().roles["gateway"]].names
    return {name.split(".")[0]: name for name in named}

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_the_waf_and_each_site_show_the_domain_learners_type(drawn_in):
    learner = project(drawn_in)
    stack = declared.read(flavor=FLAVORS[drawn_in])
    texts = [shape for shape in drawn_shapes(learner) if shape["kind"] == "text"]

    def beside(name):
        node = nodes(learner)[name]
        return " ".join(shape["text"] for shape in texts
                        if abs(shape["x"] - node["x"]) < 120 and abs(shape["y"] - node["y"]) < 100)

    assert set(domains().values()) == {"board.com", "corp.com"}
    assert all(domain in beside(stack.roles["gateway"]) for domain in domains().values())
    for role, domain in domains().items():
        site = stack.compose[role] if stack.compose[role] in nodes(learner) else stack.roles[role]
        assert domain in beside(site), (site, domain)

@pytest.mark.parametrize("drawn_in", LEARNER_MAPS, ids=LEARNER_IDS)
def test_a_learner_map_says_in_plain_words_that_gns3_never_starts_the_machines(drawn_in):
    learner = project(drawn_in)
    texts = [shape["text"] for shape in drawn_shapes(learner) if shape["kind"] == "text"]
    korean = learner["project_id"] != english_of(learner)["project_id"]

    assert [said for said in texts if "GNS3" in said and ("레인지" if korean else "range") in said]
    assert [said for said in texts if ("빨간" if korean else "red") in said and "GNS3" in said]

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

    def symbol(role):
        name = stack.compose.get(role) if stack.compose.get(role) in shown else stack.roles[role]
        return shown[name]["symbol"]

    for node in shown.values():
        if node["node_type"] == "docker":
            assert "/circle/" in node["symbol"], node["name"]
        if node["node_type"] == "qemu":
            assert "/square/" in node["symbol"] or not node["symbol"].startswith(":"), node["name"]
    assert symbol("attacker").endswith("/red/scull.svg")
    assert symbol("gateway").endswith("/green/shield.svg")
    assert {symbol(role).rsplit("/", 1)[1] for role in stack.watches} <= {"inspect.svg", "firewall.svg"}
    assert symbol("board").endswith("/blue/server.svg") and symbol("board-db").endswith("/blue/storage.svg")
    assert shown[log_store()[0]]["symbol"].endswith("/gray/statistics.svg")
