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
            """5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0"""),
    "board": ("s1_board-default", "", (), """6: eth0@if14    inet 172.18.0.3/16 brd 172.18.255.255 scope global eth0
7: eth1@if15    inet 10.30.0.184/24 brd 10.30.0.255 scope global eth1"""),
    "board-db": ("s1_board-default", "", (), """8: eth0@if16    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0"""),
    "corp-wp": ("s1_corp-default", "", (), """9: eth0@if17    inet 172.19.0.3/16 brd 172.19.255.255 scope global eth0
10: eth1@if18    inet 10.30.0.185/24 brd 10.30.0.255 scope global eth1"""),
    "corp-db": ("s1_corp-default", "", (), """11: eth0@if19    inet 172.19.0.2/16 brd 172.19.255.255 scope global eth0"""),
    "edge-sensor": ("s1_internet", "-c /etc/suricata/suricata.yaml --af-packet=sniff", ("/var/log/cr/s1/edge",),
                    """21: mgmt@if31    inet 172.29.1.11/24 brd 172.29.1.255 scope global mgmt"""),
    "estate-sensor": ("s1_estate", "-c /etc/suricata/suricata.yaml --af-packet=sniff", ("/var/log/cr/s1/estate",),
                      """23: mgmt@if33    inet 172.29.1.12/24 brd 172.29.1.255 scope global mgmt"""),
    "edge-sensor-shipper": ("container:5d1f", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid",
                            ("/opt/cr/s1/rsyslog/edge-sensor-shipper.conf", "/var/log/cr/s1/edge"), ""),
    "estate-sensor-shipper": ("container:6e2a", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid",
                              ("/opt/cr/s1/rsyslog/estate-sensor-shipper.conf", "/var/log/cr/s1/estate"), ""),
    "waf-shipper": ("s1_mgmt", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid",
                    ("/opt/cr/s1/rsyslog/waf-shipper.conf", "/var/log/cr/s1/waf/audit.log"),
                    """25: eth0@if35    inet 172.29.1.13/24 brd 172.29.1.255 scope global eth0"""),
    "log-server": ("s1_mgmt", "-n -f /etc/rsyslog.conf -i /tmp/rsyslogd.pid", ("/opt/cr/s1/rsyslog/log-server.conf",),
                   """27: eth0@if37    inet 172.29.1.10/24 brd 172.29.1.255 scope global eth0"""),
}
LEGS = {
    "kali": (("eth0", "internet", "02:42:ac:1e:01:0a"),),
    "edge": (("wan", "internet", "02:42:ac:1e:01:01"), ("lan", "estate", "02:42:0a:1e:00:01")),
    "waf": (("eth0", "estate", "02:42:0a:1e:00:b1"),),
    "board": (("eth0", "board-default", "02:42:ac:12:00:03"), ("eth1", "estate", "02:42:0a:1e:00:b8")),
    "board-db": (("eth0", "board-default", "02:42:ac:12:00:02"),),
    "corp-wp": (("eth0", "corp-default", "02:42:ac:13:00:03"), ("eth1", "estate", "02:42:0a:1e:00:b9")),
    "corp-db": (("eth0", "corp-default", "02:42:ac:13:00:02"),),
    "edge-sensor": (("sniff", "internet", "02:42:ac:1e:01:02"), ("mgmt", "mgmt", "02:42:ac:1d:01:0b")),
    "estate-sensor": (("sniff", "estate", "02:42:0a:1e:00:02"), ("mgmt", "mgmt", "02:42:ac:1d:01:0c")),
    "edge-sensor-shipper": (),
    "estate-sensor-shipper": (),
    "waf-shipper": (("eth0", "mgmt", "02:42:ac:1d:01:0d"),),
    "log-server": (("eth0", "mgmt", "02:42:ac:1d:01:0a"),),
}
FORWARDED = """@forward /var/log/cr/s1/edge/eve.json
@forward /var/log/cr/s1/estate/eve.json
@forward /var/log/cr/s1/waf/audit.log
@port 514/tcp"""


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


def fronted_by_the_waf():
    moved = said().replace("@network s1_board-default", "@network s1_board-web 8d1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 - 10.40.1.0/24 \n@network s1_board-default")
    moved = moved.replace("@leg s1_estate 02:42:0a:1e:00:b8", "@leg s1_board-web 02:42:0a:1e:00:b8")
    moved = moved.replace("7: eth1@if15    inet 10.30.0.184/24 brd 10.30.0.255 scope global eth1",
                          "7: eth1@if15    inet 10.40.1.3/24 brd 10.40.1.255 scope global eth1")
    return moved.replace("5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0",
                         "5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0\n"
                         "12: eth1@if20    inet 10.40.1.2/24 brd 10.40.1.255 scope global eth1")


def behind_one_web_bridge():
    moved = said().replace("@network s1_board-default", "@network s1_web 9e1c0d2e3a5b6c7d8e9f00112233445566778899aabbccddeeff001122334455 s1-web 10.32.0.0/24 \n@network s1_board-default")
    for mac, old, new in (("b8", "10.30.0.184/24 brd 10.30.0.255 scope global eth1", "10.32.0.59/24 brd 10.32.0.255 scope global eth1"),
                          ("b9", "10.30.0.185/24 brd 10.30.0.255 scope global eth1", "10.32.0.60/24 brd 10.32.0.255 scope global eth1")):
        moved = moved.replace(f"@leg s1_estate 02:42:0a:1e:00:{mac}", f"@leg s1_web 02:42:0a:1e:00:{mac}").replace(old, new)
    moved = moved.replace("@leg s1_estate 02:42:0a:1e:00:02", "@leg s1_web 02:42:0a:1e:00:02")
    return moved.replace("5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0",
                         "5: eth0@if13    inet 10.30.0.177/24 brd 10.30.0.255 scope global eth0\n"
                         "12: eth1@if20    inet 10.32.0.2/24 brd 10.32.0.255 scope global eth1")


def sensor_sniffing_the_web_bridge_by_name():
    wired = behind_one_web_bridge()
    start = wired.index("@container estate-sensor ")
    end = wired.index("@container ", start + 1)
    return (wired[:start] + "@container estate-sensor host\n@args -c /etc/suricata/suricata.yaml --af-packet=s1-web\n"
            "@mount /var/log/cr/s1/estate\n" + wired[end:])


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

    sniffing = {one.service: wired.legs(one)[one.sniffs] for one in wired.containers if one.sniffs}
    assert sniffing == {"edge-sensor": "internet", "estate-sensor": "estate"}
    assert {one.service for one in wired.logging()} == {
        "edge-sensor", "estate-sensor", "waf", "edge-sensor-shipper", "estate-sensor-shipper", "waf-shipper"}
    assert not {one.host for one in wired.interfaces()} & {"edge-sensor", "estate-sensor"}, (
        "a sensor's own interfaces are no learner host's")
    assert wired.port == "514/tcp"
    assert wired.network("board-default").bridge == "br-6b1c0d2e3a5b", "Docker's own name for an unnamed bridge"


def test_the_listing_reads_the_shipped_files_and_the_log_server_s_port_from_the_configs_the_slot_runs(tmp_path):
    files = rangehost.slot_files(ROOT, rangehost.Slot(1, rangehost.estate("10.30.0.0/16", 1), "dev", 1442),
                                 ("board", "corp"), declared.read().origins, declared.read().default_origin,
                                 "10.31.0.2", 5140, openstack.collected(declared.read()))
    for name, body in files.items():
        if name.startswith(f"{rangehost.SHIPPING}/"):
            (tmp_path / name).parent.mkdir(exist_ok=True)
            (tmp_path / name).write_bytes(body)
    tail = "\n".join(line for line in rangehost.WIRING.splitlines() if line.startswith("[ ! -"))
    read = subprocess.run(["sh", "-c", f'f=$1\n{tail}', "sh", str(tmp_path / rangehost.SHIPPING)],
                          capture_output=True, text=True, check=True).stdout

    assert interfaces.wiring(read, "s1").forwarded == (
        "/var/log/cr/s1/edge/eve.json", "/var/log/cr/s1/estate/eve.json", "/var/log/cr/s1/waf/audit.log")
    assert interfaces.wiring(read, "s1").port == "514/tcp"


def test_a_range_host_that_does_not_answer_is_an_outage_not_an_empty_slot():
    adapter, _ = slot_adapter(output=RangeUnavailable)

    with pytest.raises(RangeUnavailable, match="never reported"):
        adapter.wiring()


def test_web_services_behind_the_waf_are_drawn_on_the_bridge_they_share_with_it():
    drawn = board_map(output=fronted_by_the_waf())

    assert [(zone["id"], zone["caption"]) for zone in drawn["zones"]] == [
        ("internet", "internet"), ("estate", "dmz"), ("board-web", "web"), ("board-default", "database"),
        ("mgmt", "mgmt")]
    assert {pair for pair in links(drawn) if pair[1] in ("switch:estate", "switch:board-web")} == {
        ("router", "switch:estate"), ("waf", "switch:estate"), ("waf", "switch:board-web"),
        ("board.com", "switch:board-web")}
    assert links(drawn)[("board.com", "switch:board-web")] == "10.40.1.3"


def test_each_bridge_is_one_switch_and_each_interface_on_it_is_one_link_to_it():
    drawn = board_map()

    assert [zone["id"] for zone in drawn["zones"]] == ["internet", "estate", "board-default", "mgmt"]
    assert sorted(links(drawn)) == sorted([
        ("kali", "switch:internet"), ("router", "switch:internet"), ("router", "switch:estate"),
        ("waf", "switch:estate"), ("board.com", "switch:estate"), ("board.com", "switch:board-default"),
        ("board-db", "switch:board-default"), ("sensor:edge-sensor", "switch:mgmt"),
        ("sensor:estate-sensor", "switch:mgmt"), ("log-server", "switch:mgmt")])
    assert {edge["kind"] for edge in drawn["edges"]} == {"link", "mirror", "logs"}


def test_each_link_is_labelled_with_the_address_its_container_holds_on_that_bridge():
    shown = links(board_map())

    assert shown[("kali", "switch:internet")] == "5.188.10.10", "the address kali's own traffic leaves from"
    assert shown[("router", "switch:internet")] == "5.188.10.1" and shown[("router", "switch:estate")] == "10.30.0.1"
    assert shown[("waf", "switch:estate")] == "10.30.0.177" and shown[("board.com", "switch:estate")] == "10.30.0.184"
    assert shown[("board.com", "switch:board-default")] == "172.18.0.3"
    assert [zone["subnet"] for zone in board_map()["zones"]] == ["", "10.30.0.0/24", "172.18.0.0/16", "172.29.1.0/24"]
    assert shown[("sensor:edge-sensor", "switch:mgmt")] == "172.29.1.11" and shown[("log-server", "switch:mgmt")] == "172.29.1.10"


def test_a_sensor_hangs_off_the_bridge_it_sniffs_and_the_logs_go_to_the_collector_rsyslog_names():
    drawn = board_map()
    edges = {(edge["kind"], edge["source"], edge["target"]) for edge in drawn["edges"]}

    assert {("mirror", "sensor:edge-sensor", "switch:internet"),
            ("mirror", "sensor:estate-sensor", "switch:estate")} <= edges
    assert {(source, target) for kind, source, target in edges if kind == "logs"} == {("waf", "log-server")}, (
        "a sensor's shipper runs in the sensor's own network namespace, so its log goes over the 관제망 link "
        "the map draws; the WAF's log file is read by a shipper the map does not draw")
    assert {("link", "sensor:edge-sensor", "switch:mgmt"), ("link", "log-server", "switch:mgmt")} <= edges
    assert next(node for node in drawn["nodes"] if node["id"] == "log-server")["port"] == "514/tcp"


def test_a_sensor_hangs_off_the_bridge_it_sniffs_by_name_or_by_its_own_interface_on_it():
    def mirrored(output):
        return {(edge["source"], edge["target"]) for edge in board_map(output=output)["edges"]
                if edge["kind"] == "mirror"}

    assert ("sensor:estate-sensor", "switch:web") in mirrored(behind_one_web_bridge())
    assert mirrored(sensor_sniffing_the_web_bridge_by_name()) == mirrored(behind_one_web_bridge())


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


WIRINGS = pytest.mark.parametrize("output", [None, behind_one_web_bridge()], ids=["estate-shared", "web-bridge"])


def inside(node, box):
    return box[0] < node["x"] < box[2] and box[1] < node["y"] < box[3]


def nodes_of(drawn):
    return {node["id"]: node for node in drawn["nodes"]}


@WIRINGS
def test_zones_stand_left_to_right_in_the_order_traffic_reaches_them(output):
    zones = [zone for zone in board_map(output=output)["zones"] if zone["caption"] != topology.BAND]
    order = [zone["caption"] for zone in sorted(zones, key=lambda zone: zone["box"][0])]

    assert order == sorted(order, key=topology.CAPTIONS.index)
    assert all(one["box"][2] < other["box"][0] for one, other in zip(zones, zones[1:]))


@WIRINGS
def test_a_sensor_stands_in_the_management_network_straight_below_the_bridge_it_mirrors(output):
    drawn = board_map(output=output)
    placed = nodes_of(drawn)
    mirrors = [edge for edge in drawn["edges"] if edge["kind"] == "mirror"]

    flow = [zone for zone in drawn["zones"] if zone["caption"] != topology.BAND]
    [band] = [zone for zone in drawn["zones"] if zone["caption"] == topology.BAND]
    assert mirrors
    for edge in mirrors:
        sensor, bridge = placed[edge["source"]], placed[edge["target"]]
        assert not any(inside(sensor, zone["box"]) for zone in flow) and inside(sensor, band["box"]), sensor
        assert sensor["x"] == bridge["x"] and sensor["y"] > max(zone["box"][3] for zone in flow)


@WIRINGS
def test_the_management_network_runs_under_every_zone_with_the_log_server_on_it(output):
    drawn = board_map(output=output)
    placed = nodes_of(drawn)
    flow = [zone for zone in drawn["zones"] if zone["caption"] != topology.BAND]
    [band] = [zone for zone in drawn["zones"] if zone["caption"] == topology.BAND]

    assert band["box"][0] <= min(zone["box"][0] for zone in flow) and band["box"][2] >= max(zone["box"][2] for zone in flow)
    assert band["box"][1] > max(zone["box"][3] for zone in flow)
    assert inside(placed["log-server"], band["box"]) and inside(placed[f"switch:{band['id']}"], band["box"])


@WIRINGS
def test_a_device_stands_inside_its_only_zone_or_on_the_boundary_between_its_zones(output):
    drawn = board_map(output=output)
    boxes = {zone["id"]: zone["box"] for zone in drawn["zones"]}

    for node in drawn["nodes"]:
        held = node.get("zones") or ([node["zone"]] if node["kind"] == "switch" else [])
        within = {zone for zone, box in boxes.items() if inside(node, box)}
        assert within == (set(held) if len(held) == 1 else set()), node
        if len(held) > 1:
            assert boxes[held[0]][2] < node["x"] < boxes[held[-1]][0], node


@WIRINGS
def test_a_log_edge_turns_at_right_angles_and_crosses_no_other_device_or_zone(output):
    drawn = board_map(output=output)
    placed = nodes_of(drawn)
    half = topology.ICON_HALF

    for edge in (edge for edge in drawn["edges"] if edge["kind"] == "logs"):
        source, target = placed[edge["source"]], placed[edge["target"]]
        points = [(source["x"], source["y"]), *map(tuple, edge["route"]),
                  (target["x"] + edge["end"][0], target["y"] + edge["end"][1])]
        own = [zone["box"] for zone in drawn["zones"] if inside(source, zone["box"]) or inside(target, zone["box"])]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            assert x1 == x2 or y1 == y2, edge
            for node in drawn["nodes"]:
                if node["id"] not in (source["id"], target["id"]):
                    assert not (min(x1, x2) < node["x"] + half and node["x"] - half < max(x1, x2)
                                and min(y1, y2) < node["y"] + half and node["y"] - half < max(y1, y2)), (edge, node)
            for zone in drawn["zones"]:
                box = zone["box"]
                if box not in own:
                    assert not (min(x1, x2) < box[2] and box[0] < max(x1, x2)
                                and min(y1, y2) < box[3] and box[1] < max(y1, y2)), (edge, zone["id"])


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
