import hashlib
import json
import pathlib
import re

import pytest

import topology
from range import declared, openstack, sandbox, wiring
from range.ports import RangeUnavailable, Shape
from tests import docker_networks, fakecloud
from tests.sessions import open_session

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "platform"
STATIC = PLATFORM / "console" / "static" / "map"
MAP_PAGE = PLATFORM / "console" / "templates" / "console" / "map.html"
CYTOSCAPE_SHA256 = "081591ab735b2b6a3b31a3c60f8f3a3e2fee8c92939e0c7820ad1208571b6cd8"
DECLARED = declared.read()
PARAMETERS = {"key_name": "cr-platform", "control_network": "net-mgmt", "control_group": "g-cr-mgmt",
              "senders_group": "g-cr-senders",
              **{f"{kind}_{role}": f"{kind}-{role}" for kind in ("image", "flavor") for role in sandbox.ROLES},
              **{f"group_{lan}": f"g-lan-{lan}" for lan in ("internet", "dmz", "web-outer", "web-inner", "mgmt")}}


def neutron(wargame="board", slot=1):
    cloud = fakecloud.Cloud()
    plan = sandbox.plan(sandbox.read(ROOT, wargame), slot, DECLARED.origins, DECLARED.default_origin, "10.31.0.2")
    cloud.create_stack(openstack.stack_body(plan, openstack.template(plan), PARAMETERS, "digest", 30))
    tag = f"cr.slot={slot}"
    return ([one for one in cloud.networks if tag in one["tags"]], cloud.subnets,
            [one for one in cloud.ports if tag in one["tags"]])


def wired(wargame="board", slot=1, without=()):
    networks, subnets, ports = neutron(wargame, slot)
    kept = [port for port in ports if not {f"cr.device={device}" for device in without} & set(port["tags"])]
    placed = sandbox.addressed(sandbox.read(ROOT, wargame).ports, DECLARED.origins, DECLARED.default_origin)
    return wiring.from_neutron(networks, subnets, kept, {port.device: port.extra for port in placed if port.extra})


def read_slot():
    return wired().interfaces()


def learner(wargame="board"):
    return topology.learner(DECLARED, wargame, DECLARED.roles["attacker"], ("175.192.0.0/24", "73.0.0.0/24"))


def drawn_map(wargame="board", slot=1, without=()):
    return topology.graph(learner(wargame), wired(wargame, slot, without))


def links(drawn):
    return {(edge["source"], edge["target"]): edge.get("address", "") for edge in drawn["edges"]
            if edge["kind"] == "link"}


def nodes_of(drawn):
    return {node["id"]: node for node in drawn["nodes"]}


def points(edge, placed):
    source, target = placed[edge["source"]], placed[edge["target"]]
    start, end = edge.get("start") or [0, 0], edge.get("end") or [0, 0]
    return ([(source["x"] + start[0], source["y"] + start[1]), *map(tuple, edge.get("route") or ())]
            + [(target["x"] + end[0], target["y"] + end[1])])


def crosses(segment, box):
    (x1, y1), (x2, y2) = segment
    return min(x1, x2) < box[2] and box[0] < max(x1, x2) and min(y1, y2) < box[3] and box[1] < max(y1, y2)


def inside(node, box):
    return box[0] < node["x"] < box[2] and box[1] < node["y"] < box[3]


def test_neutron_s_ports_give_every_device_its_lans_and_addresses_and_leave_out_the_control_network():
    found = {(one.host, one.name, one.address, one.segment) for one in read_slot()}

    assert {("cr-kali", "internet", "5.188.10.10/24", "internet"), ("cr-kali", "internet", "73.0.0.10/24", "internet"),
            ("cr-edge", "internet", "121.134.88.42/29", "internet"), ("cr-edge", "dmz", "10.30.0.1/24", "dmz"),
            ("cr-waf", "dmz", "10.30.0.247/24", "dmz"), ("cr-waf", "web-outer", "10.30.128.247/24", "web-outer"),
            ("cr-waf", "mgmt", "172.29.0.12/24", "mgmt"), ("board", "web-inner", "10.30.128.59/24", "web-inner"),
            ("log-server", "mgmt", "172.29.0.10/24", "mgmt")} <= found
    assert not [one for one in found if one[2].startswith("10.31.")], "the platform's control network is not drawn"


def test_the_ids_is_read_with_its_two_legs_and_none_of_their_dummy_addresses():
    wires = wired()
    [ids] = [one for one in wires.containers if one.sniffs]

    assert ids.service == "cr-ids" and set(wires.legs(ids).values()) == {"web-outer", "web-inner"}
    assert ids.addresses == (), "the legs' fixed IPs are flushed at boot and stand on no interface"
    assert "10.30.128.251" not in repr(topology.graph(learner(), wires))


def test_a_slot_s_wiring_is_read_from_neutron_over_http(monkeypatch):
    cloud = fakecloud.Cloud()
    fakecloud.serving(cloud)
    openstack.forget()
    runner = fakecloud.Runner()
    monkeypatch.setattr(openstack, "execute", runner)
    runner.answer(sandbox.READY, "ready\n")
    adapter = fakecloud.adapter(cloud, slots=1)
    adapter.ensure_slot()

    assert {(one.host, one.address) for one in adapter.wiring().interfaces()} == {
        (one.host, one.address) for one in read_slot()}
    openstack.forget()


def test_the_database_zone_is_the_target_s_internal_docker_network_and_its_front_bridge_is_not_drawn():
    networks, subnets, ports = neutron()
    containers = {host.container: name for name, host in DECLARED.hosts.items() if host.container}
    wires = wiring.from_neutron(networks, subnets, ports, {}, wiring.from_docker(docker_networks.inspected(), containers))
    drawn = topology.graph(learner(), wires)

    assert [(zone["id"], zone["caption"], zone["subnet"], zone.get("owner")) for zone in drawn["zones"]
            if zone["caption"] == "database"] == [("board-backend", "database", "172.18.0.0/16", "board")]
    shown = links(drawn)
    assert shown[("board-db", "switch:board-backend")] == "172.18.0.2"
    assert shown[("board.com", "switch:board-backend")] == "172.18.0.3"
    assert shown[("board.com", "switch:web-inner")] == "10.30.128.59"
    assert "172.19.0.2" not in repr(drawn) and "172.17.0.0" not in repr(drawn), (
        "the publish bridge and docker0 carry no traffic the WAF sends; the WAF reaches the Neutron port")


def test_the_target_s_docker_networks_are_read_once_per_stack_over_ssh(monkeypatch):
    cloud = fakecloud.Cloud()
    fakecloud.serving(cloud)
    runner = fakecloud.Runner()
    monkeypatch.setattr(openstack, "execute", runner)
    runner.answer(sandbox.READY, "ready\n")
    runner.answer("docker network inspect", json.dumps(docker_networks.inspected()))
    adapter = fakecloud.adapter(cloud, slots=1)
    adapter.ensure_slot()

    for _ in range(3):
        drawn = topology.graph(learner(), fakecloud.adapter(cloud, slots=1).wiring())
    assert links(drawn)[("board-db", "switch:board-backend")] == "172.18.0.2"
    read = [sent for _, sent in runner.ran if "docker network inspect" in sent]
    assert len(read) == 1 and runner.sent_to(cloud.control_address(1, "cr-target"))[-1] == read[0]


def test_the_ids_stands_inline_between_the_waf_and_the_web_servers_switch():
    drawn = drawn_map()
    shown = links(drawn)

    assert [(zone["id"], zone["caption"]) for zone in drawn["zones"]] == [
        ("internet", "internet"), ("dmz", "dmz"), ("web-inner", "web"), ("mgmt", "mgmt")], (
        "the WAF's back leg meets only the IDS, so it is a cable, not a switch")
    assert shown[("waf", "sensor:cr-ids")] == "10.30.128.247"
    assert shown[("sensor:cr-ids", "switch:web-inner")] == ""
    assert ("waf", "switch:web-inner") not in shown and ("board.com", "switch:web-inner") in shown
    assert {edge["kind"] for edge in drawn["edges"]} == {"link"}, "no mirror, no dashed line"
    placed = nodes_of(drawn)
    assert placed["sensor:cr-ids"]["x"] == placed["switch:web-inner"]["x"]
    assert placed["waf"]["y"] < placed["sensor:cr-ids"]["y"] < placed["switch:web-inner"]["y"]


def test_each_network_is_one_switch_and_each_interface_on_it_is_one_link_to_it():
    assert sorted(links(drawn_map())) == sorted([
        ("kali", "switch:internet"), ("router", "switch:internet"), ("router", "switch:dmz"),
        ("waf", "switch:dmz"), ("waf", "sensor:cr-ids"), ("waf", "switch:mgmt"), ("sensor:cr-ids", "switch:web-inner"),
        ("board.com", "switch:web-inner"), ("log-server", "switch:mgmt")])


def test_a_corp_slot_draws_corp_and_no_board():
    drawn = drawn_map("corp", slot=2)

    assert links(drawn)[("corp.com", "switch:web-inner")] == "10.30.128.60"
    assert not {"board.com", "board-db"} & {node["id"] for node in drawn["nodes"]}


def test_each_interface_s_full_address_stands_beside_its_device_inside_the_device_s_box():
    drawn = drawn_map()
    shown = links(drawn)
    labels = {node["id"]: node for node in drawn["nodes"] if node["kind"] == "address"}
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}
    placed = nodes_of(drawn)

    assert shown[("kali", "switch:internet")] == "5.188.10.10", "the address kali's own traffic leaves from"
    assert shown[("router", "switch:internet")] == "121.134.88.42" and shown[("router", "switch:dmz")] == "10.30.0.1"
    assert [zone["subnet"] for zone in drawn["zones"]] == ["", "10.30.0.0/24", "10.30.128.0/24", "172.29.0.0/24"]
    homes = {node["id"]: None if node["kind"] == "router" else (node.get("zones") or [None])[0]
             for node in drawn["nodes"]}
    assert {(label["text"], label["zone"]) for label in labels.values()} == {
        (address, homes[source]) for (source, target), address in shown.items() if address}
    pad = topology.LABEL_PAD
    for label in labels.values():
        left, right = topology._spans(label)
        if label["zone"] is not None:
            box = boxes[label["zone"]]
            assert box[0] + pad <= left and right + pad <= box[2], label
            assert box[1] + pad <= label["y"] - topology.LINE // 2 and label["y"] + topology.LINE // 2 + pad <= box[3]
        device = placed[label["id"].split(":", 1)[1].split(":", 1)[0]]
        assert min(abs(left - device["x"]), abs(right - device["x"])) <= topology.ICON_HALF + topology.OFFSET + 8, label
        assert abs(label["y"] - device["y"]) <= topology._below(device) + topology.ADDRESS_RISE, label


def test_an_interface_with_more_addresses_than_the_one_drawn_says_how_many_more():
    labels = {node["id"]: node for node in drawn_map()["nodes"] if node["kind"] == "address"}
    origins = sum(origin.addresses for origin in DECLARED.origins)

    assert (labels["address:kali:switch:internet"]["text"], labels["address:kali:switch:internet"]["more"]) == (
        "5.188.10.10", origins - 1), "Kali speaks from every origin; the map names its default and counts the rest"
    assert "more" not in labels["address:router:switch:internet"]


def test_customer_addresses_are_not_drawn_as_a_device_or_a_label():
    assert "customers" not in repr(drawn_map()) and "175.192.0.10" not in repr(drawn_map())


def test_the_address_table_lists_every_address_the_map_draws():
    rows = topology.addresses(learner(), read_slot())
    drawn = drawn_map()
    labels = {(node["text"], node.get("more", 0)) for node in drawn["nodes"] if node["kind"] == "address"}

    assert labels <= {(row["address"], row["more"]) for row in rows}
    assert "customers" not in {row["host"] for row in rows}


def test_the_map_draws_nothing_outside_the_slot():
    text = repr(drawn_map())

    assert "10.31." not in text and "cr-slot" not in text and "cr-waf" not in text
    assert not {node["id"] for node in drawn_map()["nodes"]} & {"sw1", "sw2", "sw3", "internet"}


def test_a_device_whose_ports_are_gone_is_not_drawn():
    drawn = drawn_map(without=("cr-waf",))

    assert "waf" not in {node["id"] for node in drawn["nodes"]}
    assert ("waf", "switch:mgmt") not in links(drawn)


def test_the_waf_stands_in_the_dmz_the_ids_and_servers_in_the_web_box_and_the_router_between_boxes():
    drawn = drawn_map()
    placed = nodes_of(drawn)
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}

    assert inside(placed["waf"], boxes["dmz"]) and inside(placed["board.com"], boxes["web-inner"])
    assert inside(placed["sensor:cr-ids"], boxes["web-inner"]) and inside(placed["log-server"], boxes["mgmt"])
    assert not any(inside(placed["router"], box) for box in boxes.values())


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_no_two_zone_boxes_overlap_and_no_two_captions_read_the_same(wargame):
    drawn = drawn_map(wargame)
    boxes = [zone["box"] for zone in drawn["zones"]]

    for at, one in enumerate(boxes):
        for other in boxes[at + 1:]:
            assert not (one[0] < other[2] and other[0] < one[2] and one[1] < other[3] and other[1] < one[3])
    named = [(zone["caption"], zone.get("owner", "")) for zone in drawn["zones"]]
    assert len(set(named)) == len(named)


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_every_line_turns_at_right_angles_and_runs_through_no_icon_and_no_box_it_does_not_belong_to(wargame):
    drawn = drawn_map(wargame)
    placed = nodes_of(drawn)
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}
    half = topology.ICON_HALF
    icons = [node for node in drawn["nodes"] if node["kind"] != "address"]

    for edge in drawn["edges"]:
        source, target = placed[edge["source"]], placed[edge["target"]]
        own = set(source.get("zones") or ()) | {source.get("zone"), target.get("zone")}
        for segment in zip(points(edge, placed), points(edge, placed)[1:]):
            (x1, y1), (x2, y2) = segment
            assert x1 == x2 or y1 == y2, edge
            for node in icons:
                if node["id"] not in (source["id"], target["id"]):
                    assert not crosses(segment, [node["x"] - half, node["y"] - half,
                                                 node["x"] + half, node["y"] + half]), (edge, node["id"])
            for zone, box in boxes.items():
                if zone not in own:
                    assert not crosses(segment, box), (edge["id"], zone)


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_no_two_lines_cross(wargame):
    drawn = drawn_map(wargame)
    placed = nodes_of(drawn)
    runs = [(edge["id"], segment) for edge in drawn["edges"]
            for segment in zip(points(edge, placed), points(edge, placed)[1:])]

    for one, ((a1, b1), (a2, b2)) in runs:
        for other, ((c1, d1), (c2, d2)) in runs:
            if one != other and a1 == a2 and d1 == d2:
                assert not (min(c1, c2) < a1 < max(c1, c2) and min(b1, b2) < d1 < max(b1, b2)), (one, other)


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_address_labels_do_not_overlap_each_other_or_an_icon(wargame):
    drawn = drawn_map(wargame)
    labels = [node for node in drawn["nodes"] if node["kind"] == "address"]
    icons = [node for node in drawn["nodes"] if node["kind"] != "address"]
    half, line = topology.ICON_HALF, topology.LINE

    def area(label):
        left, right = topology._spans(label)
        return [left, label["y"] - line // 2, right, label["y"] + line // 2]

    for at, one in enumerate(labels):
        for other in labels[at + 1:]:
            assert not crosses(((area(one)[0], area(one)[1]), (area(one)[2], area(one)[3])), area(other))
        for node in icons:
            assert not crosses(((area(one)[0], area(one)[1]), (area(one)[2], area(one)[3])),
                               [node["x"] - half, node["y"] - half, node["x"] + half, node["y"] + half])


def test_the_same_wiring_is_laid_out_the_same_on_every_slot_and_every_read():
    def where(drawn):
        return ({node["id"]: (node["x"], node["y"]) for node in drawn["nodes"]},
                {zone["caption"]: zone["box"] for zone in drawn["zones"]})

    assert where(drawn_map()) == where(drawn_map()) == where(drawn_map(slot=2))


@pytest.mark.django_db
def test_the_session_topology_carries_the_live_map_of_its_slot(client, monkeypatch):
    from api import views

    class Slot:
        def describe(self):
            return Shape(segments=(), sensors=())

        def wiring(self):
            return wired()

    session_id = open_session(client)
    monkeypatch.setattr(views, "_range", lambda session=None, **_: Slot())

    drawn = client.get(f"/api/sessions/{session_id}/topology/").json()["map"]

    assert ("board.com", "switch:web-inner") in links(drawn) and drawn["zones"][1]["caption"] == "dmz"


@pytest.mark.django_db
def test_a_slot_that_cannot_be_read_gives_an_empty_map_that_says_why(client, monkeypatch):
    from api import views

    class Slot:
        def describe(self):
            return Shape(segments=(), sensors=())

        def wiring(self):
            raise RangeUnavailable("GET http://neutron/v2.0/ports answered 503: down")

    session_id = open_session(client)
    monkeypatch.setattr(views, "_range", lambda session=None, **_: Slot())

    drawn = client.get(f"/api/sessions/{session_id}/topology/").json()["map"]

    assert drawn["nodes"] == [] and "answered 503" in drawn["detail"]


def test_the_map_page_is_framed_only_by_its_own_origin(client):
    answer = client.get("/map/1/")

    assert answer.status_code == 200 and answer["X-Frame-Options"] == "SAMEORIGIN"


def test_the_map_page_draws_from_the_api_with_the_vendored_library_and_lets_nothing_be_edited():
    page = MAP_PAGE.read_text()

    assert '<script src="/static/map/cytoscape.min.js"></script>' in page
    assert "fetch(`/api/sessions/${session}/topology/`)" in page
    assert "autoungrabify: true, autounselectify: true, boxSelectionEnabled: false" in page
    assert "userPanningEnabled: true" in page and "userZoomingEnabled: true" in page
    assert not re.search(r"setInterval\([^)]*fetch|topology/`\)[^;]*setInterval", page), "the wiring is read once"


def test_the_map_asks_for_its_icons_before_the_library_loads_and_draws_once_they_are_in():
    page = MAP_PAGE.read_text()
    library = page.index('<script src="/static/map/cytoscape.min.js"></script>')

    assert page.index("image.src = symbolUrl(file);") < library
    assert page.index("fetch(`/api/sessions/${session}/topology/`)") < library
    assert page.index("await symbolsLoaded;") < page.index("view.cy = cytoscape({")


def test_the_vendored_cytoscape_is_the_pinned_release_and_every_symbol_the_page_names_is_served():
    assert hashlib.sha256((STATIC / "cytoscape.min.js").read_bytes()).hexdigest() == CYTOSCAPE_SHA256
    assert CYTOSCAPE_SHA256 in (STATIC / "SOURCES").read_text()
    named = set(re.findall(r'"([\w-]+\.svg)"', MAP_PAGE.read_text()))
    assert named and named <= {path.name for path in (STATIC / "symbols").glob("*.svg")}
    assert "location /static/map/ {\n            alias /app/console/static/map/;" in (PLATFORM / "nginx.conf").read_text()
