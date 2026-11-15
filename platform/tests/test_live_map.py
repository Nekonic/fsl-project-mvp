import hashlib
import pathlib
import re
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
@network s1_board-default 6b1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 172.18.0.0/16
@network s1_corp-default 7c1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 172.19.0.0/16 """
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
            """5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0"""),
    "board": ("s1_board-default", "", (), """6: eth0@if14    inet 172.18.0.3/16 brd 172.18.255.255 scope global eth0
7: eth1@if15    inet 10.30.0.184/24 brd 10.30.0.255 scope global eth1"""),
    "board-db": ("s1_board-default", "", (), """8: eth0@if16    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0"""),
    "corp-wp": ("s1_corp-default", "", (), """9: eth0@if17    inet 172.19.0.3/16 brd 172.19.255.255 scope global eth0
10: eth1@if18    inet 10.30.0.185/24 brd 10.30.0.255 scope global eth1"""),
    "corp-db": ("s1_corp-default", "", (), """11: eth0@if19    inet 172.19.0.2/16 brd 172.19.255.255 scope global eth0"""),
    "edge-sensor": ("host", "-c /etc/suricata/suricata.yaml --af-packet=s1-inet", ("/var/log/cr/s1/edge",), ""),
    "estate-sensor": ("host", "-c /etc/suricata/suricata.yaml --af-packet=s1-estate", ("/var/log/cr/s1/estate",), ""),
}
LEGS = {
    "kali": (("eth0", "internet", "02:42:ac:1e:01:0a"),),
    "edge": (("wan", "internet", "02:42:ac:1e:01:01"), ("lan", "estate", "02:42:0a:1e:00:01")),
    "waf": (("eth0", "estate", "02:42:0a:1e:00:b1"),),
    "board": (("eth0", "board-default", "02:42:ac:12:00:03"), ("eth1", "estate", "02:42:0a:1e:00:b8")),
    "board-db": (("eth0", "board-default", "02:42:ac:12:00:02"),),
    "corp-wp": (("eth0", "corp-default", "02:42:ac:13:00:03"), ("eth1", "estate", "02:42:0a:1e:00:b9")),
    "corp-db": (("eth0", "corp-default", "02:42:ac:13:00:02"),),
    "edge-sensor": (("", "host", ""),),
    "estate-sensor": (("", "host", ""),),
}
FORWARDED = """@forward /var/log/cr/s1/edge/eve.json
@port 5140
@forward /var/log/cr/s1/estate/eve.json
@port 5140
@forward /var/log/cr/s1/waf/audit.log
@port 5140"""


def said(without=()):
    blocks = [NETWORKS]
    for service, (mode, args, mounts, addresses) in CONTAINERS.items():
        if service in without:
            continue
        links = [f"{at}: {name}@if{at + 20}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1442 qdisc noqueue state UP "
                 f"mode DEFAULT group default \\    link/ether {mac} brd ff:ff:ff:ff:ff:ff link-netnsid 0"
                 for at, (name, _, mac) in enumerate(LEGS[service], start=2) if mac]
        blocks.append("\n".join([f"@container {service} {mode}", f"@args {args}",
                                 *(f"@mount {mount}" for mount in mounts),
                                 *(f"@leg {'s1_' + network if mac else network} {mac}"
                                   for _, network, mac in LEGS[service]), ""]
                                + ([*links, addresses] if addresses else [])))
    return "\n".join(blocks + [FORWARDED]) + "\n"


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


def slot_adapter(without=(), output=None):
    adapter = object.__new__(openstack.OpenStack)
    adapter.declared = declared.read()
    adapter.slot = 1
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


def board_map(without=(), output=None):
    adapter, _ = slot_adapter(without, output)
    return topology.graph(board_learner(), adapter.wiring())


def fronted_by_the_waf():
    moved = said().replace("@network s1_board-default", "@network s1_board-web 8d1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 10.40.1.0/24 \n@network s1_board-default")
    moved = moved.replace("@leg s1_estate 02:42:0a:1e:00:b8", "@leg s1_board-web 02:42:0a:1e:00:b8")
    moved = moved.replace("7: eth1@if15    inet 10.30.0.184/24 brd 10.30.0.255 scope global eth1",
                          "7: eth1@if15    inet 10.40.1.3/24 brd 10.40.1.255 scope global eth1")
    return moved.replace("5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0",
                         "5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0\n"
                         "12: eth1@if20    inet 10.40.1.2/24 brd 10.40.1.255 scope global eth1")


def links(drawn):
    return {(edge["source"], edge["target"]): edge.get("address", "") for edge in drawn["edges"]
            if edge["kind"] == "link"}


def test_one_read_on_the_range_host_gives_every_container_its_networks_and_addresses():
    adapter, fake = slot_adapter()
    found = {(one.host, one.name, one.address, one.segment) for one in adapter.wiring().interfaces()}

    assert {("cr-kali", "eth0", "5.188.10.10/24", "internet"), ("cr-kali", "eth0", "172.30.1.10/24", "internet"),
            ("cr-edge", "wan", "73.0.0.1/24", "internet"), ("cr-edge", "lan", "10.30.0.1/24", "estate"),
            ("cr-waf", "eth0", "10.30.0.177/24", "estate"), ("board", "eth1", "10.30.0.184/24", "estate"),
            ("board", "eth0", "172.18.0.3/16", "board-default"),
            ("corp-db", "eth0", "172.19.0.2/16", "corp-default")} <= found
    assert fake.ran == [("", rangehost.wiring("s1"))], "one ssh round trip lists the whole slot"


def test_a_sensor_is_read_with_the_bridge_it_sniffs_and_the_logs_by_the_files_rsyslog_forwards():
    wired = interfaces.wiring(said(), "s1")

    sniffing = {one.service: wired.bridged(one.sniffs).key for one in wired.containers if one.sniffs}
    assert sniffing == {"edge-sensor": "internet", "estate-sensor": "estate"}
    assert {one.service for one in wired.logging()} == {"edge-sensor", "estate-sensor", "waf"}
    assert wired.port == "5140"
    assert wired.network("board-default").bridge == "br-6b1c0d2e3a5b", "Docker's own name for an unnamed bridge"


def test_a_range_host_that_does_not_answer_is_an_outage_not_an_empty_slot():
    adapter, _ = slot_adapter(output=RangeUnavailable)

    with pytest.raises(RangeUnavailable, match="never reported"):
        adapter.wiring()


def test_web_services_behind_the_waf_are_drawn_on_the_bridge_they_share_with_it():
    drawn = board_map(output=fronted_by_the_waf())

    assert [(zone["id"], zone["caption"]) for zone in drawn["zones"]] == [
        ("internet", "internet"), ("estate", "dmz"), ("board-web", "web"), ("board-default", "database")]
    assert {pair for pair in links(drawn) if pair[1] in ("switch:estate", "switch:board-web")} == {
        ("router", "switch:estate"), ("waf", "switch:estate"), ("waf", "switch:board-web"),
        ("board.com", "switch:board-web")}
    assert links(drawn)[("board.com", "switch:board-web")] == "10.40.1.3"


def test_each_bridge_is_one_switch_and_each_interface_on_it_is_one_link_to_it():
    drawn = board_map()

    assert [zone["id"] for zone in drawn["zones"]] == ["internet", "estate", "board-default"]
    assert sorted(links(drawn)) == sorted([
        ("kali", "switch:internet"), ("router", "switch:internet"), ("router", "switch:estate"),
        ("waf", "switch:estate"), ("board.com", "switch:estate"), ("board.com", "switch:board-default"),
        ("board-db", "switch:board-default")])
    assert {edge["kind"] for edge in drawn["edges"]} == {"link", "mirror", "logs"}


def test_each_link_is_labelled_with_the_address_its_container_holds_on_that_bridge():
    shown = links(board_map())

    assert shown[("kali", "switch:internet")] == "5.188.10.10", "the address kali's own traffic leaves from"
    assert shown[("router", "switch:internet")] == "5.188.10.1" and shown[("router", "switch:estate")] == "10.30.0.1"
    assert shown[("waf", "switch:estate")] == "10.30.0.177" and shown[("board.com", "switch:estate")] == "10.30.0.184"
    assert shown[("board.com", "switch:board-default")] == "172.18.0.3"
    assert [zone["subnet"] for zone in board_map()["zones"]] == ["", "10.30.0.0/24", "172.18.0.0/16"]


def test_a_sensor_hangs_off_the_bridge_it_sniffs_and_the_logs_go_to_the_collector_rsyslog_names():
    drawn = board_map()
    edges = {(edge["kind"], edge["source"], edge["target"]) for edge in drawn["edges"]}

    assert {("mirror", "sensor:edge-sensor", "switch:internet"),
            ("mirror", "sensor:estate-sensor", "switch:estate")} <= edges
    assert {(source, target) for kind, source, target in edges if kind == "logs"} == {
        ("sensor:edge-sensor", "log-server"), ("sensor:estate-sensor", "log-server"), ("waf", "log-server")}
    assert next(node for node in drawn["nodes"] if node["id"] == "log-server")["port"] == "5140/udp"


def test_customers_are_addresses_on_kali_and_not_a_device():
    drawn = board_map()
    kali = next(node for node in drawn["nodes"] if node["id"] == "kali")

    assert "customers" not in {node["id"] for node in drawn["nodes"]}
    assert kali["customers"] == {"address": "175.192.0.10", "more": 2}


def test_the_map_shows_its_own_wargame_and_no_management_platform_or_device_name():
    drawn = board_map()
    text = repr(drawn)

    assert "corp" not in text and "172.19." not in text
    assert "10.31." not in text and "cr-" not in text and "s1-" not in text and "s1_" not in text
    assert not {node["id"] for node in drawn["nodes"]} & {"sw1", "sw2", "sw3", "internet"}


def test_a_stopped_container_is_not_drawn():
    drawn = board_map(without=("waf",))

    assert "waf" not in {node["id"] for node in drawn["nodes"]}
    assert ("waf", "log-server") not in {(edge["source"], edge["target"]) for edge in drawn["edges"]}


@pytest.mark.django_db
def test_the_session_topology_carries_the_live_map_of_its_slot(client, monkeypatch):
    from api import views

    adapter, _ = slot_adapter()
    session_id = open_session(client)
    monkeypatch.setattr(views, "_range", lambda session=None, **_: adapter)

    drawn = client.get(f"/api/sessions/{session_id}/topology/").json()["map"]

    assert ("board.com", "switch:estate") in links(drawn) and drawn["zones"][1]["caption"] == "dmz"


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
