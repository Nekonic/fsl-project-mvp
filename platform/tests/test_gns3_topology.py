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

    assert all(str(uuid.UUID(value)) == value for value in ids)
    assert len(ids) == len(set(ids))
    assert len({project(path)["name"] for path in EVERY_MAP}) == 6

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
    stack = declared.read(flavor=flavor_of(gns3))
    for wargame in WARGAMES:
        shown = learner_of(stack, wargame)
        drawn = {name for name in switches if name not in shown.hidden}
        defended = {shown.switches[segment] for segment in defended_ids()}
        bridges = {switch for segment, switch in shown.switches.items() if segment.endswith(topology.BRIDGE_SUFFIX)}
        assert defended <= drawn and topology.MONITORING in drawn, wargame
        assert drawn - defended - {topology.MONITORING} <= bridges, wargame
        assert fabric.MANAGEMENT not in shown.switches, "no switch stands for the management segment"

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

LEARNER_MAPS = [DOCKER, DOCKER_KO, OPENSTACK, OPENSTACK_KO]
LEARNER_IDS = ["docker", "docker-ko", "openstack", "openstack-ko"]
WARGAMES = sorted(yaml.safe_load(declared.DECLARATION.read_text())["hosts"]["fsl-waf"]["names"])
WARGAMES = [name.split(".")[0] for name in WARGAMES]
PROJECTED = [(path, wargame) for path in LEARNER_MAPS for wargame in WARGAMES]
PROJECTED_IDS = [f"{name}-{wargame}" for name in LEARNER_IDS for wargame in WARGAMES]
IDLE = "sleep 2147483647"
WARGAME_HOST_WORDS = ("wargame", "fsl-", "mgmt", "anagement", "_default", "-default")

def flavor_of(document):
    return "openstack" if english_of(document)["project_id"] == project(OPENSTACK)["project_id"] else ""

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
    stack = declared.read(flavor=FLAVORS[path])
    return topology.for_wargame(project(path), learner_of(stack, wargame)), learner_of(stack, wargame), stack

def log_store():
    service = composed.services()["elasticsearch"]
    return service["container_name"], image(service)

def ends(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    return {frozenset((by_id[end["node_id"]]["name"], end["adapter_number"], end["port_number"])
                      for end in link["nodes"]) for link in document["topology"]["links"]}

def network_mode(stack, flavor, role):
    services = yaml.safe_load(SENSOR_COMPOSE.read_text())["services"] if flavor else composed.services()
    return (services.get(stack.compose.get(role, "")) or {}).get("network_mode", "")

def nic_owner(stack, flavor, role):
    mode = network_mode(stack, flavor, role)
    if mode.startswith("service:"):
        shared = mode.removeprefix("service:")
        return next(stack.roles[other] for other, service in stack.compose.items() if service == shared)
    return stack.roles[role]

def log_sources(stack, flavor):
    if flavor:
        senders = {stack.roles["gateway"]} | {stack.roles[role] for role in stack.watches}
        return senders | {host for host, entry in stack.hosts.items() if entry.logs}
    services = yaml.safe_load(composed.SESSION.read_text())["services"]
    shipped = {volume.split(":")[0] for name, service in services.items()
               if fabric.MANAGEMENT in network_keys(service) and name not in stack.compose.values()
               for volume in service.get("volumes") or []}
    return {nic_owner(stack, flavor, role) for role in ("gateway", *stack.watches)
            if shipped & {volume.split(":")[0] for volume in services[stack.compose[role]].get("volumes") or []}}

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
    system = project(SYSTEMS[drawn_in])
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
    english = [shape["text"] for shape in drawn_shapes(english_of(document)) if shape["kind"] == "text"]
    scorer = declared.read(flavor=FLAVORS[drawn_in]).roles["scorer"]
    named = [node["name"] for node in document["topology"]["nodes"]] + [document["name"]]

    assert [said for said in english if scorer in said or "mgmt" in said or "anagement" in said] == []
    assert [said for said in english + named if any(word in said for word in WARGAME_HOST_WORDS)] == []
    assert "fsl-" not in json.dumps(document)

@pytest.mark.parametrize("drawn_in, wargame", PROJECTED, ids=PROJECTED_IDS)
def test_the_log_server_sits_on_the_monitoring_switch_with_exactly_the_hosts_whose_records_reach_it(drawn_in, wargame):
    learner, shown, stack = projected(drawn_in, wargame)
    flavor = FLAVORS[drawn_in]
    sources = {shown.shown(host) for host in log_sources(stack, flavor)}

    assert shown.hosts[log_store()[0]] == (topology.LOG_SERVER,)
    assert wiring(learner)[topology.LOG_SERVER] == {topology.MONITORING}
    assert monitoring_ends(learner) == sources | {topology.LOG_SERVER}
    assert not {topology.ATTACKER, topology.CUSTOMERS} & monitoring_ends(learner)
    assert flavor != "openstack" or sources == {topology.WAF, topology.FIREWALL, topology.domains(stack)[wargame]}, (
        "the WAF's and the edge's logs and the estate sensor on the sites' host reach the store")
    assert flavor == "openstack" or sources == {topology.WAF}, (
        "on Docker the shipper reads the WAF's audit log and the sensor in the WAF's namespace, nothing of the site")

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
