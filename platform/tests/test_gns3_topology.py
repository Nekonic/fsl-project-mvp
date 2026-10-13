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

@pytest.fixture(params=[DOCKER, OPENSTACK], ids=["docker", "openstack"])
def gns3(request):
    return project(request.param)

def test_both_projects_are_revision_9_so_gns3_2_2_opens_them_and_3_upgrades_them(gns3):
    assert gns3["revision"] == 9
    assert gns3["type"] == "topology"
    assert set(gns3) <= GNS3_2_2_TOP_LEVEL, sorted(set(gns3) - GNS3_2_2_TOP_LEVEL)
    assert set(gns3["topology"]) == GNS3_2_2_TOPOLOGY
    assert gns3["topology"]["computes"] == []

def test_every_id_in_a_project_is_a_uuid_and_unique(gns3):
    ids = [gns3["project_id"]]
    ids += [node["node_id"] for node in gns3["topology"]["nodes"]]
    ids += [link["link_id"] for link in gns3["topology"]["links"]]
    ids += [drawing["drawing_id"] for drawing in gns3["topology"]["drawings"]]

    assert all(str(uuid.UUID(value)) == value for value in ids)
    assert len(ids) == len(set(ids))

def test_every_node_name_is_an_rfc1123_hostname_so_gns3_3_keeps_it(gns3):
    names = [node["name"] for node in gns3["topology"]["nodes"]]

    assert [name for name in names if not RFC1123.match(name)] == []
    assert len(names) == len(set(names))
    assert {node["compute_id"] for node in gns3["topology"]["nodes"]} == {"local"}

def test_every_link_joins_two_ports_that_exist_and_no_port_twice(gns3):
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

def test_no_qemu_node_names_a_disk_so_the_project_opens_without_images(gns3):
    for node in gns3["topology"]["nodes"]:
        if node["node_type"] == "qemu":
            disks = {k: v for k, v in node["properties"].items() if k.endswith("_disk_image")}
            assert set(disks.values()) <= {""}, node["name"]

def test_the_segments_are_the_declared_segments_as_switches(gns3):
    declared_segments, _ = segment_ids()
    switches = {name for name, node in nodes(gns3).items() if node["node_type"] == SWITCH}

    assert declared_segments <= switches
    assert not {name for name in switches - declared_segments if not name.endswith("-default")}

def test_the_docker_project_is_the_compose_stack_one_container_per_service():
    gns3 = project(DOCKER)
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

def test_every_host_a_docker_role_names_is_a_node_of_the_docker_project():
    drawn = nodes(project(DOCKER))

    assert set(declared.read().roles.values()) <= set(drawn)

def test_the_openstack_project_is_the_declared_hosts_and_the_wargame_hosts_containers():
    gns3 = project(OPENSTACK)
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
    gns3 = project(OPENSTACK)
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

def test_every_drawing_is_one_shape_both_gns3_releases_draw_in_a_font_the_web_ui_has(gns3):
    texts = [shape for shape in drawn_shapes(gns3) if shape["kind"] == "text"]

    assert texts
    assert {shape["font"] for shape in texts} == {"Noto Sans"}

def test_each_declared_segment_is_a_titled_zone_holding_its_switch(gns3):
    entries = yaml.safe_load(declared.DECLARATION.read_text())["segments"]
    shapes = drawn_shapes(gns3)
    zones = [shape for shape in shapes if shape["kind"] == "rect"]
    switches = nodes(gns3)
    for entry in entries:
        titles = [shape for shape in shapes if shape["kind"] == "text" and shape["text"].startswith(entry["name"])]
        assert len(titles) == 1, entry["name"]
        holding = [zone for zone in zones if inside(titles[0]["x"], titles[0]["y"], zone)
                   and inside(switches[entry["id"]]["x"] + 25, switches[entry["id"]]["y"] + 25, zone)]
        assert holding, f"{entry['name']}: no zone holds both its title and the {entry['id']} switch"

def test_a_node_with_no_nic_says_whose_network_it_watches_next_to_it(gns3):
    linked = {end["node_id"] for link in gns3["topology"]["links"] for end in link["nodes"]}
    names = set(nodes(gns3))
    texts = [shape for shape in drawn_shapes(gns3) if shape["kind"] == "text"]
    unlinked = [node for node in gns3["topology"]["nodes"] if node["node_id"] not in linked]

    assert unlinked
    for node in unlinked:
        near = [shape["text"] for shape in texts
                if abs(shape["x"] - node["x"]) < 250 and abs(shape["y"] - node["y"]) < 150]
        assert [said for said in near if "host network" in said or any(
            name in said for name in names - {node["name"]})], (node["name"], near)
