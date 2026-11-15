import hashlib
import pathlib
import re
import subprocess
from types import SimpleNamespace

import pytest

import topology
from range import declared, interfaces, openstack, rangehost
from range.ports import Node, Ran, RangeUnavailable, Segment, Shape
from tests.sessions import open_session

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "platform"
STATIC = PLATFORM / "console" / "static" / "map"
MAP_PAGE = PLATFORM / "console" / "templates" / "console" / "map.html"
DEFAULT_ORIGIN = "5.188.10.0/24"
CYTOSCAPE_SHA256 = "081591ab735b2b6a3b31a3c60f8f3a3e2fee8c92939e0c7820ad1208571b6cd8"

NETWORKS = """@network s1_internet 4f1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 s1-inet 172.30.1.0/24
@network s1_estate 5a1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 s1-estate 10.30.0.0/24
@network s1_web 9e1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 s1-web 10.32.0.0/24
@network s1_board-default 6b1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 172.18.0.0/16
@network s1_corp-default 7c1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 172.19.0.0/16
@network s1_mgmt 8a1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 s1-mgmt 172.29.1.0/24 """
CONTAINERS = {
    "kali": ("s1_internet", "", (), """2: eth0@if10    inet 172.30.1.10/24 brd 172.30.1.255 scope global eth0\\       valid_lft forever
2: eth0@if10    inet 73.0.0.10/24 scope global eth0\\       valid_lft forever preferred_lft forever
2: eth0@if10    inet 73.0.0.11/24 scope global secondary eth0
2: eth0@if10    inet 175.192.0.10/24 scope global eth0
2: eth0@if10    inet 5.188.10.10/24 scope global eth0\\       valid_lft forever preferred_lft forever"""),
    "edge": ("s1_estate", "", (), """3: wan@if11    inet 73.0.0.1/24 scope global wan
3: wan@if11    inet 5.188.10.1/24 scope global wan
4: lan@if12    inet 10.30.0.1/24 brd 10.30.0.255 scope global lan"""),
    "waf": ("s1_estate", "", ("/var/log/cr/s1/waf/audit.log",),
            """5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0
12: eth1@if20    inet 10.32.0.2/24 brd 10.32.0.255 scope global eth1
13: mgmt@if21    inet 172.29.1.12/24 brd 172.29.1.255 scope global mgmt"""),
    "board": ("s1_board-default", "", (), """6: eth0@if14    inet 172.18.0.3/16 brd 172.18.255.255 scope global eth0
7: eth1@if15    inet 10.32.0.59/24 brd 10.32.0.255 scope global eth1"""),
    "board-db": ("s1_board-default", "", (), """8: eth0@if16    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0"""),
    "corp-wp": ("s1_corp-default", "", (), """9: eth0@if17    inet 172.19.0.3/16 brd 172.19.255.255 scope global eth0
10: eth1@if18    inet 10.32.0.60/24 brd 10.32.0.255 scope global eth1"""),
    "corp-db": ("s1_corp-default", "", (), """11: eth0@if19    inet 172.19.0.2/16 brd 172.19.255.255 scope global eth0"""),
    "sensor": ("s1_web", "-c /etc/suricata/suricata.yaml --af-packet", (),
               """23: mgmt@if33    inet 172.29.1.11/24 brd 172.29.1.255 scope global mgmt"""),
    "sensor-shipper": ("container:5d1f", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid",
                       ("/opt/cr/s1/rsyslog/sensor-shipper.conf", "/var/log/cr/s1/sensor"), ""),
    "waf-shipper": ("container:6e2a", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid",
                    ("/opt/cr/s1/rsyslog/waf-shipper.conf", "/var/log/cr/s1/waf/audit.log"), ""),
    "log-server": ("s1_mgmt", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid", ("/opt/cr/s1/rsyslog/log-server.conf",),
                   """27: eth0@if37    inet 172.29.1.10/24 brd 172.29.1.255 scope global eth0"""),
}
LEGS = {
    "kali": (("eth0", "internet", "02:42:ac:1e:01:0a"),),
    "edge": (("wan", "internet", "02:42:ac:1e:01:01"), ("lan", "estate", "02:42:0a:1e:00:01")),
    "waf": (("eth0", "estate", "02:42:0a:1e:00:b1"), ("eth1", "web", "02:42:0a:20:00:02"),
            ("mgmt", "mgmt", "02:42:ac:1d:01:0c")),
    "board": (("eth0", "board-default", "02:42:ac:12:00:03"), ("eth1", "web", "02:42:0a:20:00:3b")),
    "board-db": (("eth0", "board-default", "02:42:ac:12:00:02"),),
    "corp-wp": (("eth0", "corp-default", "02:42:ac:13:00:03"), ("eth1", "web", "02:42:0a:20:00:3c")),
    "corp-db": (("eth0", "corp-default", "02:42:ac:13:00:02"),),
    "sensor": (("web", "web", "02:42:0a:20:00:05"), ("mgmt", "mgmt", "02:42:ac:1d:01:0b")),
    "sensor-shipper": (),
    "waf-shipper": (),
    "log-server": (("eth0", "mgmt", "02:42:ac:1d:01:0a"),),
}
def said(without=()):
    blocks = [NETWORKS]
    for service, (mode, args, _, addresses) in CONTAINERS.items():
        if service in without:
            continue
        links = [f"{at}: {name}@if{at + 20}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1442 qdisc noqueue state UP "
                 f"mode DEFAULT group default \\    link/ether {mac} brd ff:ff:ff:ff:ff:ff link-netnsid 0"
                 for at, (name, _, mac) in enumerate(LEGS[service], start=2) if mac]
        blocks.append("\n".join([f"@container {service} {mode}", f"@args {args}",
                                 *(f"@leg {'s1_' + network if mac else network} {mac}"
                                   for _, network, mac in LEGS[service]), ""]
                                + ([*links, addresses] if addresses else [])))
    return "\n".join(blocks) + "\n"


class FakeSlot:
    def __init__(self, without, output=None):
        self.without = without
        self.output = output
        self.ran = []

    def shell(self, container=""):
        def run(argv, stdin=None, timeout=60.0):
            self.ran.append((container, argv))
            if self.output is RangeUnavailable:
                raise RangeUnavailable("cr-range at 10.31.0.5 never reported the command finishing")
            return Ran(0, self.output if self.output is not None else said(self.without))
        return run


def slot_shape():
    return Shape(segments=(
        Segment(id="ru", name="Russia", subnet=DEFAULT_ORIGIN, nodes=(Node("cr-kali", "5.188.10.10"),)),
        Segment(id="estate", name="Application estate", subnet="10.30.0.0/24", nodes=(Node("cr-waf", "10.30.0.177"),)),
        Segment(id="mgmt", name="Management", subnet="10.31.0.0/24", nodes=(Node("cr-platform", "10.31.0.238"),)),
    ), sensors=())


def slot_adapter(without=(), output=None, slot=1):
    adapter = object.__new__(openstack.OpenStack)
    adapter.declared = declared.read()
    adapter.slot = slot
    adapter.build = openstack.Build(source=str(ROOT), inside={"estate": "10.30.0.0/16", "mgmt": "10.31.0.0/24"},
                                    image_tag="dev", mtu=1442)
    fake = FakeSlot(without, output)
    adapter._shell = fake.shell
    adapter.describe = slot_shape
    return adapter, fake


def read_slot():
    adapter, _ = slot_adapter()
    return adapter.wiring().interfaces()


def board_learner():
    stack = declared.read()
    return topology.learner(stack, "board", stack.roles["attacker"], ("175.192.0.0/24", "73.0.0.0/24"))


def board_map(without=(), output=None, slot=1):
    adapter, _ = slot_adapter(without, output, slot)
    return topology.graph(board_learner(), adapter.wiring())


def sensor_sniffing_the_web_bridge_by_name():
    wired = said()
    start = wired.index("@container sensor ")
    end = wired.index("@container ", start + 1)
    return (wired[:start] + "@container sensor host\n@args -c /etc/suricata/suricata.yaml --af-packet=s1-web\n"
            + wired[end:])


def links(drawn):
    return {(edge["source"], edge["target"]): edge.get("address", "") for edge in drawn["edges"]
            if edge["kind"] == "link"}


def test_one_read_on_the_range_host_gives_every_container_its_networks_and_addresses():
    adapter, fake = slot_adapter()
    found = {(one.host, one.name, one.address, one.segment) for one in adapter.wiring().interfaces()}

    assert {("cr-kali", "eth0", "5.188.10.10/24", "internet"), ("cr-kali", "eth0", "172.30.1.10/24", "internet"),
            ("cr-edge", "wan", "73.0.0.1/24", "internet"), ("cr-edge", "lan", "10.30.0.1/24", "estate"),
            ("cr-waf", "eth0", "10.30.0.177/24", "estate"), ("cr-waf", "eth1", "10.32.0.2/24", "web"),
            ("cr-waf", "mgmt", "172.29.1.12/24", "mgmt"), ("board", "eth1", "10.32.0.59/24", "web"),
            ("board", "eth0", "172.18.0.3/16", "board-default"),
            ("corp-db", "eth0", "172.19.0.2/16", "corp-default")} <= found
    assert fake.ran == [("", rangehost.wiring("s1"))], "one ssh round trip lists the whole slot"


def test_the_sensor_is_read_with_the_network_it_sniffs():
    wired = interfaces.wiring(said(), "s1")

    sniffing = {one.service: sorted(wired.legs(one)[name] for name in one.sniffs)
                for one in wired.containers if one.sniffs}
    assert sniffing == {"sensor": ["web"]}, "a sniffing interface is the sensor's one with no address"
    assert "sensor" not in {one.host for one in wired.interfaces()}, "a sensor's own interfaces are no learner host's"
    assert wired.network("board-default").bridge == "br-6b1c0d2e3a5b", "Docker's own name for an unnamed bridge"


def test_a_range_host_that_does_not_answer_is_an_outage_not_an_empty_slot():
    adapter, _ = slot_adapter(output=RangeUnavailable)

    with pytest.raises(RangeUnavailable, match="never reported"):
        adapter.wiring()


def test_web_services_behind_the_waf_are_drawn_on_the_bridge_they_share_with_it():
    drawn = board_map()

    assert [(zone["id"], zone["caption"]) for zone in drawn["zones"]] == [
        ("internet", "internet"), ("estate", "dmz"), ("web", "web"), ("board-default", "database"),
        ("corp-default", "database"), ("mgmt", "mgmt")]
    assert {pair for pair in links(drawn) if pair[1] in ("switch:estate", "switch:web")} == {
        ("router", "switch:estate"), ("waf", "switch:estate"), ("waf", "switch:web"), ("board.com", "switch:web"),
        ("corp.com", "switch:web")}
    assert links(drawn)[("board.com", "switch:web")] == "10.32.0.59"


def test_each_bridge_is_one_switch_and_each_interface_on_it_is_one_link_to_it():
    drawn = board_map()

    assert sorted(links(drawn)) == sorted([
        ("kali", "switch:internet"), ("router", "switch:internet"), ("router", "switch:estate"),
        ("waf", "switch:estate"), ("waf", "switch:web"), ("waf", "switch:mgmt"), ("board.com", "switch:web"),
        ("board.com", "switch:board-default"), ("board-db", "switch:board-default"), ("corp.com", "switch:web"),
        ("corp.com", "switch:corp-default"), ("corp-db", "switch:corp-default"),
        ("sensor:sensor", "switch:mgmt"), ("log-server", "switch:mgmt")])
    assert {edge["kind"] for edge in drawn["edges"]} == {"link", "mirror"}


def test_each_interface_s_full_address_stands_beside_its_link_inside_the_box_of_its_subnet():
    drawn = board_map()
    shown = links(drawn)
    labels = {node["id"]: node for node in drawn["nodes"] if node["kind"] == "address"}
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}

    assert shown[("kali", "switch:internet")] == "5.188.10.10", "the address kali's own traffic leaves from"
    assert shown[("router", "switch:internet")] == "5.188.10.1" and shown[("router", "switch:estate")] == "10.30.0.1"
    assert shown[("waf", "switch:estate")] == "10.30.0.177" and shown[("board.com", "switch:board-default")] == "172.18.0.3"
    assert [zone["subnet"] for zone in drawn["zones"]] == [
        "", "10.30.0.0/24", "10.32.0.0/24", "172.18.0.0/16", "172.19.0.0/16", "172.29.1.0/24"]
    assert {(label["text"], label["zone"]) for label in labels.values()} == {
        (address, target.removeprefix("switch:")) for (_, target), address in shown.items()}
    for label in labels.values():
        left, right = topology._spans(label)
        box = boxes[label["zone"]]
        assert box[0] < left and right < box[2] and box[1] < label["y"] < box[3], label
    assert not [edge for edge in drawn["edges"] if edge.get("label") or edge.get("host")], "nothing is written mid-line"


def test_the_sensor_watches_the_web_servers_behind_the_waf_and_reports_on_the_management_network():
    drawn = board_map()
    edges = {(edge["kind"], edge["source"], edge["target"]) for edge in drawn["edges"]}

    assert {(source, target) for kind, source, target in edges if kind == "mirror"} == {("sensor:sensor", "switch:web")}
    assert {("link", "sensor:sensor", "switch:mgmt"), ("link", "waf", "switch:mgmt"),
            ("link", "log-server", "switch:mgmt")} <= edges
    assert not [node for node in drawn["nodes"] if node["kind"] in ("collector", "host")], (
        "the log path ends at the log server; the range host and the platform are not the learner's network")


def test_a_sensor_hangs_off_the_bridge_it_sniffs_by_name_or_by_its_own_interface_on_it():
    def mirrored(output):
        return {(edge["source"], edge["target"]) for edge in board_map(output=output)["edges"]
                if edge["kind"] == "mirror"}

    assert mirrored(None) == {("sensor:sensor", "switch:web")}
    assert mirrored(sensor_sniffing_the_web_bridge_by_name()) == {("sensor:sensor", "switch:web")}


def test_customer_addresses_are_not_drawn_as_a_device_or_a_label():
    drawn = board_map()

    assert "customers" not in repr(drawn) and "175.192.0.10" not in repr(drawn)


def test_the_map_draws_every_target_the_slot_runs_and_nothing_outside_the_slot():
    drawn = board_map()
    text = repr(drawn)

    assert {"board.com", "board-db", "corp.com", "corp-db"} <= {node["id"] for node in drawn["nodes"]}
    assert [zone.get("owner") for zone in drawn["zones"] if zone["caption"] == "database"] == ["board", "corp"]
    assert "10.31." not in text and "cr-" not in text and "s1-" not in text and "s1_" not in text
    assert not {node["id"] for node in drawn["nodes"]} & {"sw1", "sw2", "sw3", "internet"}


def test_a_board_session_s_slot_draws_board_alone_once_corp_is_stopped():
    drawn = board_map(without=("corp-wp", "corp-db"))

    assert not {"corp.com", "corp-db"} & {node["id"] for node in drawn["nodes"]}
    assert [zone.get("owner") for zone in drawn["zones"] if zone["caption"] == "database"] == ["board"]


def test_a_stopped_container_is_not_drawn():
    drawn = board_map(without=("waf",))

    assert "waf" not in {node["id"] for node in drawn["nodes"]}
    assert ("waf", "switch:mgmt") not in {(edge["source"], edge["target"]) for edge in drawn["edges"]}


def inside(node, box):
    return box[0] < node["x"] < box[2] and box[1] < node["y"] < box[3]


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


def test_the_waf_stands_in_the_dmz_the_web_servers_in_their_segment_and_the_router_on_the_boundary():
    drawn = board_map()
    placed = nodes_of(drawn)
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}

    assert inside(placed["waf"], boxes["estate"]) and inside(placed["switch:estate"], boxes["estate"])
    assert inside(placed["board.com"], boxes["web"]) and inside(placed["corp.com"], boxes["web"])
    assert not any(inside(placed["router"], box) for box in boxes.values())
    assert boxes["internet"][2] <= placed["router"]["x"] - topology.ICON_HALF
    assert placed["router"]["x"] + topology.ICON_HALF <= boxes["estate"][0]
    assert inside(placed["sensor:sensor"], boxes["mgmt"]) and inside(placed["log-server"], boxes["mgmt"])
    assert inside(placed["board-db"], boxes["board-default"]) and inside(placed["corp-db"], boxes["corp-default"])


def test_no_two_zone_boxes_overlap_and_no_two_captions_read_the_same():
    drawn = board_map()
    boxes = [zone["box"] for zone in drawn["zones"]]

    for at, one in enumerate(boxes):
        for other in boxes[at + 1:]:
            assert not (one[0] < other[2] and other[0] < one[2] and one[1] < other[3] and other[1] < one[3])
    named = [(zone["caption"], zone.get("owner", "")) for zone in drawn["zones"]]
    assert len(set(named)) == len(named)


def test_every_line_turns_at_right_angles_and_runs_through_no_icon_and_no_box_it_does_not_belong_to():
    drawn = board_map()
    placed = nodes_of(drawn)
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}
    half = topology.ICON_HALF
    icons = [node for node in drawn["nodes"] if node["kind"] != "address"]

    for edge in drawn["edges"]:
        source, target = placed[edge["source"]], placed[edge["target"]]
        own = set(source.get("zones") or ()) | {source.get("zone"), target["zone"]}
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


def test_no_two_lines_run_side_by_side():
    drawn = board_map()
    placed = nodes_of(drawn)
    runs = [(edge["id"], segment) for edge in drawn["edges"]
            for segment in zip(points(edge, placed), points(edge, placed)[1:])]

    for at, (one, ((a1, b1), (a2, b2))) in enumerate(runs):
        for other, ((c1, d1), (c2, d2)) in runs[at + 1:]:
            if one == other:
                continue
            if a1 == a2 and c1 == c2 and abs(a1 - c1) < 40:
                assert min(max(b1, b2), max(d1, d2)) - max(min(b1, b2), min(d1, d2)) < 80, (one, other)
            if b1 == b2 and d1 == d2 and abs(b1 - d1) < 40:
                assert min(max(a1, a2), max(c1, c2)) - max(min(a1, a2), min(c1, c2)) < 80, (one, other)


def test_address_labels_do_not_overlap_each_other_or_an_icon():
    drawn = board_map()
    labels = [node for node in drawn["nodes"] if node["kind"] == "address"]
    icons = [node for node in drawn["nodes"] if node["kind"] != "address"]
    half, line = topology.ICON_HALF, topology.LINE

    def area(label):
        left, right = topology._spans(label)
        return [left, label["y"] - line // 2, right, label["y"] + line // 2]

    for at, one in enumerate(labels):
        for other in labels[at + 1:]:
            assert not crosses(((area(one)[0], area(one)[1]), (area(one)[2], area(one)[3])), area(other)), (
                one["text"], other["text"])
        for node in icons:
            assert not crosses(((area(one)[0], area(one)[1]), (area(one)[2], area(one)[3])),
                               [node["x"] - half, node["y"] - half, node["x"] + half, node["y"] + half]), (
                one["text"], node["id"])


def test_the_same_wiring_is_laid_out_the_same_on_every_slot_and_every_read():
    def where(drawn):
        return ({node["id"]: (node["x"], node["y"]) for node in drawn["nodes"]},
                {zone["caption"]: zone["box"] for zone in drawn["zones"]})

    second = said().replace("s1", "s2").replace("10.30.0.", "10.30.1.")

    assert where(board_map()) == where(board_map()) == where(board_map(output=second, slot=2))


@pytest.mark.django_db
def test_the_session_topology_carries_the_live_map_of_its_slot(client, monkeypatch):
    from api import views

    adapter, _ = slot_adapter()
    session_id = open_session(client)
    monkeypatch.setattr(views, "_range", lambda session=None, **_: adapter)

    drawn = client.get(f"/api/sessions/{session_id}/topology/").json()["map"]

    assert ("board.com", "switch:web") in links(drawn) and drawn["zones"][1]["caption"] == "dmz"


@pytest.mark.django_db
def test_a_range_host_that_cannot_be_read_gives_an_empty_map_that_says_why(client, monkeypatch):
    from api import views

    adapter, _ = slot_adapter(output=RangeUnavailable)
    session_id = open_session(client)
    monkeypatch.setattr(views, "_range", lambda session=None, **_: adapter)

    drawn = client.get(f"/api/sessions/{session_id}/topology/").json()["map"]

    assert drawn["nodes"] == [] and "never reported the command finishing" in drawn["detail"]


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


def test_the_vendored_cytoscape_is_the_pinned_release_and_every_symbol_the_page_names_is_served():
    assert hashlib.sha256((STATIC / "cytoscape.min.js").read_bytes()).hexdigest() == CYTOSCAPE_SHA256
    assert CYTOSCAPE_SHA256 in (STATIC / "SOURCES").read_text()
    named = set(re.findall(r'"([\w-]+\.svg)"', MAP_PAGE.read_text()))
    assert named and named <= {path.name for path in (STATIC / "symbols").glob("*.svg")}
    assert "location /static/map/ {\n            alias /app/console/static/map/;" in (PLATFORM / "nginx.conf").read_text()
