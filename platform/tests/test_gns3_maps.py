import dataclasses
import io
import json
import re
import pathlib
import uuid
import zipfile
from types import SimpleNamespace
from xml.etree import ElementTree
from unittest.mock import patch

import pytest
import yaml
from django.test import override_settings

import gns3
import topology
from api import maps
from range import declared, docker, interfaces, openstack
from range.interfaces import Interface
from range.ports import Node, Ran, RangeUnavailable, Segment, Shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "deploy" / "topology"
OPENSTACK = TOPOLOGY / "range-openstack.gns3"
OPENSTACK_KO = TOPOLOGY / "range-openstack.ko.gns3"
DOCKER = TOPOLOGY / "range-docker.gns3"
LABEL_KEYS = {"text", "style", "x", "y", "rotation"}
SWITCH = "ethernet_switch"
DEFAULT_ORIGIN = "5.188.10.0/24"
LABEL = re.compile(r"[a-z][a-z0-9]* \.\d{1,3}")
KOREAN_SUFFIX = json.loads(OPENSTACK_KO.read_text())["name"].removeprefix("fsl-range-openstack")

KALI_IP = """1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
2: ens3    inet 73.0.0.10/24 scope global ens3\\       valid_lft forever preferred_lft forever
2: ens3    inet 5.188.10.10/24 scope global ens3\\       valid_lft forever preferred_lft forever
3: ens4    inet 10.31.0.59/24 metric 100 brd 10.31.0.255 scope global dynamic ens4\\       valid_lft 1sec
"""
EDGE_IFCONFIG = """vtnet0: flags=1008843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST,LOWER_UP> metric 0 mtu 1450
\tdescription: internet (wan)
\tinet 73.0.0.1 netmask 0xffffff00 broadcast 73.0.0.255
\tinet 5.188.10.1 netmask 0xffffff00 broadcast 5.188.10.255
vtnet1: flags=1008843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST,LOWER_UP> metric 0 mtu 1450
\tinet 10.30.0.1 netmask 0xffffff00 broadcast 10.30.0.255
vtnet2: flags=1008843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST,LOWER_UP> metric 0 mtu 1450
\tinet 10.31.0.78 netmask 0xffffff00 broadcast 10.31.0.255
lo0: flags=1008049<UP,LOOPBACK,RUNNING,MULTICAST,LOWER_UP> metric 0 mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
"""
WAF_IP = """2: ens3    inet 10.30.0.177/24 metric 100 scope global dynamic ens3
3: ens4    inet 10.31.0.195/24 metric 100 scope global dynamic ens4
"""
HOST_IP = """2: ens3    inet 10.30.0.184/24 metric 100 scope global dynamic ens3
3: ens4    inet 10.31.0.134/24 metric 100 scope global dynamic ens4
4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
1125: br-7cc6b1febc1d    inet 172.18.0.1/16 brd 172.18.255.255 scope global br-7cc6b1febc1d
1128: br-228fc957cc76    inet 172.19.0.1/16 brd 172.19.255.255 scope global br-228fc957cc76
"""
HOST_CONTAINERS = """@network 7cc6b1febc1d0000000000000000000000000000000000000000000000000000 board_default
@network 228fc957cc760000000000000000000000000000000000000000000000000000 corp_default
@network 0f0f0f0f0f0f0000000000000000000000000000000000000000000000000000 bridge
@container board
42: eth0@if43    inet 172.18.0.3/16 brd 172.18.255.255 scope global eth0
@container board-db
40: eth0@if41    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0
@container corp-wp
44: eth0@if45    inet 172.19.0.3/16 brd 172.19.255.255 scope global eth0
@container corp-db
46: eth0@if47    inet 172.19.0.2/16 brd 172.19.255.255 scope global eth0
"""

def slot_shape(estate_waf="10.30.0.177"):
    return Shape(segments=(
        Segment(id="ru", name="Russia", subnet=DEFAULT_ORIGIN, nodes=(Node("fsl-kali", "5.188.10.10"),)),
        Segment(id="us", name="United States", subnet="73.0.0.0/24", nodes=(Node("fsl-kali", "73.0.0.10"),)),
        Segment(id="estate", name="Application estate", subnet="10.30.0.0/24",
                nodes=(Node("fsl-waf", estate_waf),)),
        Segment(id="mgmt", name="Management", subnet="10.31.0.0/24", nodes=()),
    ), sensors=())

class FakeSlot:
    def __init__(self, said):
        self.said = said
        self.ran = []

    def runner(self, role):
        def run(argv, stdin=None, timeout=60.0):
            self.ran.append((role, argv))
            if role == "wargames" and argv[0] == "sudo":
                return Ran(0, HOST_CONTAINERS)
            if role not in self.said:
                raise RangeUnavailable(f"{role} did not answer")
            return Ran(0, self.said[role])
        return run

def slot_adapter(said=None, shape=None):
    adapter = object.__new__(openstack.OpenStack)
    adapter.declared = declared.read(flavor="openstack")
    fake = FakeSlot(said if said is not None else
                    {"attacker": KALI_IP, "edge": EDGE_IFCONFIG, "gateway": WAF_IP, "wargames": HOST_IP})
    adapter.runner = fake.runner
    adapter.describe = lambda: shape or slot_shape()
    return adapter, fake

def read_slot():
    adapter, _ = slot_adapter()
    return adapter.interfaces()

def held(found):
    return {(one.host, one.name, one.address, one.segment) for one in found}

def test_ip_and_ifconfig_output_are_read_as_interfaces_and_loopback_is_left_out():
    assert interfaces.listed(KALI_IP) == [("ens3", "73.0.0.10/24"), ("ens3", "5.188.10.10/24"),
                                          ("ens4", "10.31.0.59/24")]
    assert interfaces.listed(EDGE_IFCONFIG) == [("vtnet0", "73.0.0.1/24"), ("vtnet0", "5.188.10.1/24"),
                                                ("vtnet1", "10.30.0.1/24"), ("vtnet2", "10.31.0.78/24")]

def test_a_slot_s_interfaces_come_from_each_host_and_the_wargame_host_s_containers_on_their_own_bridges():
    adapter, fake = slot_adapter()
    found = held(adapter.interfaces())

    assert {("fsl-kali", "ens3", "5.188.10.10/24", "internet"), ("fsl-kali", "ens4", "10.31.0.59/24", "mgmt"),
            ("fsl-edge", "vtnet0", "73.0.0.1/24", "internet"), ("fsl-edge", "vtnet1", "10.30.0.1/24", "estate"),
            ("fsl-waf", "ens3", "10.30.0.177/24", "estate"),
            ("fsl-wargame-host", "ens3", "10.30.0.184/24", "estate"),
            ("fsl-wargame-host", "br-7cc6b1febc1d", "172.18.0.1/16", "board-default"),
            ("board", "eth0", "172.18.0.3/16", "board-default"),
            ("corp-db", "eth0", "172.19.0.2/16", "corp-default")} <= found
    assert ("fsl-wargame-host", "docker0", "172.17.0.1/16", "") in found, "a bridge no wargame uses is no segment"
    assert {role for role, _ in fake.ran} == {"attacker", "edge", "gateway", "wargames"}, (
        "each host is read over a role that runs on the host itself, never inside a wargame container"
    )
    assert ["sudo", "sh", "-c", interfaces.CONTAINERS] in [argv for _, argv in fake.ran]

def test_a_host_that_does_not_answer_leaves_its_own_labels_empty_and_the_rest_are_read():
    adapter, _ = slot_adapter({"attacker": KALI_IP, "gateway": WAF_IP, "wargames": HOST_IP})

    assert "fsl-edge" not in {one.host for one in adapter.interfaces()}
    assert "fsl-kali" in {one.host for one in adapter.interfaces()}

def test_a_docker_session_s_interfaces_are_named_by_matching_each_endpoint_s_mac_inside_its_container():
    stack = docker.Docker(declared=declared.read(), project="fsl", session=7)
    networks = [
        {"Name": "fsl-7_origin-ru", "Labels": {docker.SEGMENT_LABEL: "ru"}, "Containers": {
            "a": {"Name": "fsl-7-kali-1", "MacAddress": "02:42:ac:00:00:0a", "IPv4Address": "5.188.10.3/24"},
            "b": {"Name": "fsl-7-waf-1", "MacAddress": "02:42:ac:00:00:0b", "IPv4Address": "5.188.10.4/24"},
            "c": {"Name": "fsl-platform", "MacAddress": "02:42:ac:00:00:0c", "IPv4Address": "5.188.10.2/24"}}},
        {"Name": "fsl-7_estate", "Labels": {docker.SEGMENT_LABEL: "estate"}, "Containers": {
            "d": {"Name": "fsl-7-waf-1", "MacAddress": "02:42:ac:00:01:0b", "IPv4Address": "172.30.0.3/24"}}},
    ]
    macs = {"fsl-7-kali-1": "eth0 02:42:ac:00:00:0a\nlo 00:00:00:00:00:00\n",
            "fsl-7-waf-1": "eth0 02:42:ac:00:01:0b\neth1 02:42:AC:00:00:0B\n"}
    execs = []

    def read(argv):
        execs.append(argv[1])
        return macs[argv[1]]

    with patch.object(docker.Docker, "_networks", return_value=(networks, "fsl-7")), \
         patch.object(docker.Docker, "_read", side_effect=read):
        found = held(stack.interfaces({"fsl-kali", "fsl-waf"}))

    assert found == {("fsl-kali", "eth0", "5.188.10.3/24", "internet"),
                     ("fsl-waf", "eth1", "5.188.10.4/24", "internet"),
                     ("fsl-waf", "eth0", "172.30.0.3/24", "estate")}
    assert sorted(execs) == ["fsl-7-kali-1", "fsl-7-waf-1"], "a container off the learner's map is not read"

def slot_map(number=2, path=OPENSTACK, found=None):
    flavor = "openstack" if path in (OPENSTACK, OPENSTACK_KO) else ""
    called = topology.shown_as(declared.read(flavor=flavor))
    found = found if found is not None else read_slot()
    return topology.labelled(json.loads(path.read_text()),
                             [dataclasses.replace(one, host=called.get(one.host, one.host)) for one in found],
                             f"slot-{number}", f"slot {number}", DEFAULT_ORIGIN)

def labels(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    shown = {}
    for link in document["topology"]["links"]:
        one, other = (by_id[end["node_id"]] for end in link["nodes"])
        shown[(one["name"], other["name"])] = link["nodes"][0]["label"]
        shown[(other["name"], one["name"])] = link["nodes"][1]["label"]
    return shown

def test_every_link_end_of_a_slot_s_map_names_the_interface_and_its_address_on_that_segment():
    shown = {pair: label["text"] for pair, label in labels(slot_map()).items()}

    assert shown[("fsl-kali", "internet")] == "ens3 .10", "the default origin's address, and only it"
    assert shown[("fsl-edge", "internet")] == "vtnet0 .1"
    assert shown[("fsl-edge", "estate")] == "vtnet1 .1"
    assert shown[("fsl-waf", "estate")] == "ens3 .177"
    assert shown[("fsl-wargame-host", "board-default")] == "", "the host's side of a Docker bridge carries no label"
    assert shown[("board.com", "board-default")] == "eth0 .3"
    assert shown[("corp-db", "corp-default")] == "eth0 .2"
    assert all(text == "" for (one, _), text in shown.items() if one in {"internet", "estate", "board-default",
                                                                          "corp-default", "monitoring"})
    assert all(text == "" for (_, other), text in shown.items() if other == "monitoring")
    assert not [text for text in shown.values() if "10.31.0." in text], "no management address reaches the map"

def test_each_slot_s_map_carries_its_own_addresses_and_ids_and_keeps_every_drawing():
    english = json.loads(OPENSTACK.read_text())
    one = slot_map(1, found=[Interface("fsl-waf", "ens3", "10.30.0.102/24", "estate")])
    two = slot_map(2)
    ids = lambda document: ({document["project_id"]} | {n["node_id"] for n in document["topology"]["nodes"]}
                            | {link["link_id"] for link in document["topology"]["links"]}
                            | {d["drawing_id"] for d in document["topology"]["drawings"]})

    assert labels(one)[("fsl-waf", "estate")]["text"] == "ens3 .102"
    assert labels(two)[("fsl-waf", "estate")]["text"] == "ens3 .177"
    assert not ids(one) & ids(two) and not ids(one) & ids(english) and not ids(two) & ids(english)
    assert two["project_id"] == str(uuid.uuid5(uuid.UUID(english["project_id"]), "slot-2"))
    assert one["name"] == "fsl-range-openstack slot 1" and two["show_interface_labels"] is True
    assert [d["svg"] for d in two["topology"]["drawings"] if "<rect" in d["svg"]] == [
        d["svg"] for d in english["topology"]["drawings"] if "<rect" in d["svg"]]
    assert [(n["name"], n["symbol"], n["x"], n["y"]) for n in two["topology"]["nodes"]] == [
        (n["name"], n["symbol"], n["x"], n["y"]) for n in english["topology"]["nodes"]]

def test_the_korean_slot_map_keeps_its_language_in_the_name_and_differs_in_id_from_the_english_one():
    korean = slot_map(2, OPENSTACK_KO)

    assert KOREAN_SUFFIX.startswith(" (") and korean["name"] == "fsl-range-openstack slot 2" + KOREAN_SUFFIX
    assert korean["project_id"] != slot_map(2)["project_id"]
    assert labels(korean)[("fsl-waf", "estate")]["text"] == "ens3 .177"

@pytest.mark.parametrize("path", [OPENSTACK, OPENSTACK_KO, DOCKER], ids=["openstack", "openstack-ko", "docker"])
def test_a_generated_map_is_a_gns3_2_2_project_whose_labels_fit_both_releases_schemas(path):
    document = slot_map(2, path)
    from tests.test_gns3_topology import GNS3_2_2_TOP_LEVEL, GNS3_2_2_TOPOLOGY
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}

    assert document["revision"] == 9 and document["type"] == "topology"
    assert set(document) <= GNS3_2_2_TOP_LEVEL and set(document["topology"]) == GNS3_2_2_TOPOLOGY
    for link in document["topology"]["links"]:
        assert len(link["nodes"]) == 2
        for end in link["nodes"]:
            assert end["node_id"] in by_id
            assert set(end["label"]) == LABEL_KEYS
            assert isinstance(end["label"]["text"], str) and isinstance(end["label"]["style"], str)
            assert all(isinstance(end["label"][axis], int) for axis in ("x", "y", "rotation"))
            assert -359 <= end["label"]["rotation"] <= 360
    ids = [document["project_id"], *by_id, *(link["link_id"] for link in document["topology"]["links"]),
           *(drawing["drawing_id"] for drawing in document["topology"]["drawings"])]
    assert len(ids) == len(set(ids)) and all(str(uuid.UUID(value)) == value for value in ids)

def test_a_label_sits_on_the_side_of_its_node_that_faces_the_link():
    shown = labels(slot_map())

    assert shown[("fsl-kali", "internet")]["x"] > 30, "internet is right of Kali, so the label is too"
    assert shown[("internet", "fsl-kali")]["x"] < 30

@pytest.mark.parametrize("path", [OPENSTACK, OPENSTACK_KO, DOCKER], ids=["openstack", "openstack-ko", "docker"])
def test_every_label_lies_level_clear_of_its_node_on_the_side_its_link_leaves(path):
    document = slot_map(2, path)
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    size = topology.SYMBOL_SIZE
    for link in document["topology"]["links"]:
        ends = [by_id[end["node_id"]] for end in link["nodes"]]
        for end, node, other in ((link["nodes"][0], *ends), (link["nodes"][1], *ends[::-1])):
            label = end["label"]
            across, down = topology.leaving(node, other)
            below = other["y"] < node["y"]
            assert label["rotation"] == 0
            if across > 0:
                assert label["x"] > size and (label["y"] > size // 2) == below and topology.STARTS in label["style"]
            elif across < 0:
                assert label["x"] < 0 and (label["y"] > size // 2) == below and topology.ENDS in label["style"]
            elif down > 0:
                assert label["y"] > size and label["x"] > size // 2
            else:
                assert label["y"] < 0 and label["x"] > size // 2

@pytest.mark.parametrize("path", [OPENSTACK, OPENSTACK_KO, DOCKER], ids=["openstack", "openstack-ko", "docker"])
def test_a_label_shows_one_address_and_never_a_docker_bridge_name(path):
    found = read_slot() + [Interface("fsl-waf", "eth1", "5.188.10.4/24", "internet"),
                           Interface("fsl-waf", "eth2", "73.0.0.4/24", "internet")]
    texts = [label["text"] for label in labels(slot_map(2, path, found)).values()]

    assert [text for text in texts if text and not LABEL.fullmatch(text)] == []
    assert any(text for text in texts)

class Served:
    def __init__(self, opened=()):
        self.published, self.removed = [], []
        self.opened = set(opened)

    def publish(self, document):
        self.published.append(document)
        self.opened.add(document["project_id"])
        return "opened"

    def status(self, project_id):
        return "opened" if project_id in self.opened else ""

    def remove_except(self, named, kept):
        stale = [project_id for project_id in self.opened if project_id not in kept and named]
        self.removed.append((named, sorted(kept)))
        return stale

@pytest.fixture
def served(settings, monkeypatch):
    settings.FSL_TOPOLOGY = OPENSTACK
    settings.RANGE = declared.read(flavor="openstack")
    fake = Served()
    for name in ("publish", "status", "remove_except"):
        monkeypatch.setattr(gns3, name, getattr(fake, name))
    maps._loaded.clear()
    maps._found.clear()
    return fake

def test_a_slot_s_maps_are_loaded_in_both_languages_and_not_again_while_nothing_changed(served):
    maps.publish("slot 2", read_slot)
    maps.publish("slot 2", read_slot)

    assert [document["name"] for document in served.published] == [
        "fsl-range-openstack slot 2", "fsl-range-openstack slot 2" + KOREAN_SUFFIX]
    assert {document["project_id"] for document in served.published} == {
        maps.project_id("slot 2", "en"), maps.project_id("slot 2", "ko")}

def test_a_changed_address_loads_the_slot_s_maps_again(served):
    maps.publish("slot 2", read_slot)
    maps.publish("slot 2", lambda: [Interface("fsl-waf", "ens3", "10.30.0.99/24", "estate")])

    assert len(served.published) == 4
    assert labels(served.published[-2])[("fsl-waf", "estate")]["text"] == "ens3 .99"

def test_tidying_keeps_only_the_maps_of_the_slots_or_sessions_still_standing(served):
    maps.tidy(maps.SESSION, ["session 4"])

    kept = sorted({maps.project_id("session 4", language) for language in ("en", "ko")})
    assert served.removed == [("fsl-range-openstack session ", kept)] * 2, (
        "both languages' maps share the base name, and a canonical map never matches the prefix"
    )

def test_the_map_served_for_a_session_is_its_slot_s_project_once_gns3_holds_it_open(served, monkeypatch):
    monkeypatch.setattr(gns3, "project", lambda language, kept=None: {"project_id": (kept or {}).get("project_id")})

    shown = maps.served("slot 2", "ko", read_slot)

    assert shown["project_id"] == maps.project_id("slot 2", "ko")
    assert len(served.published) == 2, "a map GNS3 did not hold yet is loaded before it is served"

def test_a_map_that_cannot_be_loaded_falls_back_to_the_range_s_own_map_and_says_why(served, monkeypatch):
    def refused(document):
        raise gns3.Unavailable("GNS3 refused the admin sign-in")

    monkeypatch.setattr(gns3, "publish", refused)
    monkeypatch.setattr(gns3, "project", lambda language, kept=None: {"project_id": "canonical", "detail": ""})

    shown = maps.served("slot 1", "en", read_slot)

    assert shown["project_id"] == "canonical" and "admin sign-in" in shown["detail"]

def test_publishing_replaces_the_project_by_import_and_opens_it_as_admin(settings, tmp_path):
    settings.FSL_GNS3_URL = "http://gns3:3080"
    settings.FSL_GNS3_ADMIN_PASSWORD = ""
    secret = tmp_path / "admin-password"
    secret.write_text("s3cret\n")
    settings.FSL_GNS3_ADMIN_PASSWORD_FILE = secret
    document = slot_map(2)
    calls = []

    def answer(method):
        def reply(url, **kwargs):
            calls.append((method, url.split("/v3")[1], kwargs))
            body = {"access_token": "t"} if url.endswith("/authenticate") else {"status": "opened"}
            return SimpleNamespace(status_code=404 if method == "delete" else 200, json=lambda: body,
                                   raise_for_status=lambda: None)
        return reply

    with patch("gns3.requests.post", side_effect=answer("post")), \
         patch("gns3.requests.delete", side_effect=answer("delete")):
        assert gns3.publish(document) == "opened"

    project_id = document["project_id"]
    assert [(method, path) for method, path, _ in calls] == [
        ("post", "/access/users/authenticate"), ("delete", f"/projects/{project_id}"),
        ("post", f"/projects/{project_id}/import"), ("post", f"/projects/{project_id}/open")]
    assert calls[0][2]["json"] == {"username": "admin", "password": "s3cret"}
    archive = zipfile.ZipFile(io.BytesIO(calls[2][2]["data"]))
    assert json.loads(archive.read("project.gns3")) == document, (
        "an import whose project.gns3 keeps the URL's project id keeps every id, as GNS3 restores a snapshot"
    )

def test_without_an_admin_password_no_map_is_loaded_and_the_reason_is_said(settings, tmp_path):
    settings.FSL_GNS3_URL = "http://gns3:3080"
    settings.FSL_GNS3_ADMIN_PASSWORD = ""
    settings.FSL_GNS3_ADMIN_PASSWORD_FILE = tmp_path / "missing"

    with pytest.raises(gns3.Unavailable, match="admin password"):
        gns3.publish(slot_map(2))

@pytest.mark.django_db
def test_the_topology_endpoint_serves_the_session_s_own_map_when_gns3_runs(client):
    from tests.sessions import open_session

    session_id = open_session(client)
    with override_settings(FSL_GNS3_URL="http://gns3:3080"), \
         patch("api.views._map_key", return_value="session 9"), \
         patch.object(maps, "served", return_value={"project": {"name": "mine"}, "web_ui": None}) as asked:
        found = client.get(f"/api/topology/?language=ko&session={session_id}").json()
        refused = client.get("/api/topology/?session=x")

    assert found["project"] == {"name": "mine"}
    assert asked.call_args.args[:2] == ("session 9", "ko")
    assert refused.status_code == 400

PROC_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
ens3\t00000000\t01001E0A\t0003\t0\t0\t100\t00000000\t0\t0\t0
ens3\t00001E0A\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
"""
NETSTAT = """Routing tables

Internet:
Destination        Gateway            Flags     Netif Expire
default            5.188.10.254       UGS      vtnet0
10.30.0.0/24       link#2             U        vtnet1
"""
CONTAINER_ROUTE = "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"

def test_the_default_route_is_read_from_proc_or_netstat_and_held_by_the_interface_it_leaves_by():
    waf = interfaces.placed("fsl-waf", WAF_IP + PROC_ROUTE, [("10.30.0.0/24", "estate")])
    edge = interfaces.placed("fsl-edge", EDGE_IFCONFIG + NETSTAT, [])

    assert interfaces.routed(PROC_ROUTE) == {"ens3": "10.30.0.1"}
    assert interfaces.routed(NETSTAT) == {"vtnet0": "5.188.10.254"}
    assert {(one.name, one.gateway) for one in waf} == {("ens3", "10.30.0.1"), ("ens4", "")}
    assert {one.gateway for one in edge if one.name == "vtnet0"} == {"5.188.10.254"}
    assert interfaces.ROUTES in interfaces.LISTED and interfaces.ROUTES in interfaces.MACS
    assert "-n cat /proc/net/route" in interfaces.CONTAINERS

def caption_texts(document):
    return [ElementTree.fromstring(d["svg"])[0].text for d in document["topology"]["drawings"] if "<text" in d["svg"]]

@pytest.mark.parametrize("path", [OPENSTACK, OPENSTACK_KO], ids=["openstack", "openstack-ko"])
def test_each_zone_caption_on_a_slot_s_map_carries_the_network_its_segment_holds_on_the_range(path):
    template, drawn = json.loads(path.read_text()), slot_map(2, path)
    networks = {"internet": DEFAULT_ORIGIN, "estate": "10.30.0.0/24",
                "board-default": "172.18.0.0/16", "corp-default": "172.19.0.0/16"}
    before = {segment: ElementTree.fromstring(d["svg"])[0].text for segment, d in topology.captions(template).items()}
    after = {segment: ElementTree.fromstring(d["svg"])[0].text for segment, d in topology.captions(drawn).items()}

    assert set(after) == {*networks, "monitoring"}
    assert after == {segment: f"{before[segment]} {networks[segment]}" if segment in networks else before[segment]
                     for segment in before}
    assert not [text for text in caption_texts(drawn) if "10.31.0." in text], "no management network is named"
    assert "fsl-wargame-host" in caption_texts(drawn), "the box around the containers names their host and nothing else"

def routed_slot():
    said = {"attacker": KALI_IP, "edge": EDGE_IFCONFIG + NETSTAT, "gateway": WAF_IP + PROC_ROUTE,
            "wargames": HOST_IP + PROC_ROUTE}
    adapter, _ = slot_adapter(said)
    containers = HOST_CONTAINERS.replace("@container board-db", CONTAINER_ROUTE + "@container board-db")
    original = adapter.runner

    def runner(role):
        run = original(role)
        return lambda argv, **kwargs: Ran(0, containers) if role == "wargames" and argv[0] == "sudo" else run(argv, **kwargs)
    adapter.runner = runner
    return adapter.interfaces()

def test_the_addressing_table_lists_each_device_s_interfaces_on_the_learner_s_segments_and_the_services(settings):
    settings.RANGE = declared.read(flavor="openstack")
    found = maps.shown(routed_slot())
    table = topology.addressing(json.loads(OPENSTACK.read_text()), settings.RANGE, found, DEFAULT_ORIGIN)
    rows = {(row["device"], row["interface"]): row for row in table["devices"]}

    assert rows[("fsl-kali", "ens3")]["address"] == "5.188.10.10/24", "the default origin's address, as on the map"
    assert rows[("fsl-waf", "ens3")] == {"device": "fsl-waf", "interface": "ens3", "address": "10.30.0.177/24",
                                         "segment": "estate", "gateway": "10.30.0.1"}
    assert rows[("fsl-edge", "vtnet0")]["gateway"] == "5.188.10.254" and rows[("fsl-edge", "vtnet1")]["gateway"] == ""
    assert rows[("board.com", "eth0")] == {"device": "board.com", "interface": "eth0", "address": "172.18.0.3/16",
                                           "segment": "board-default", "gateway": "172.18.0.1"}
    assert ("fsl-wargame-host", "br-7cc6b1febc1d") in rows, "the containers' gateway is listed with its interface"
    assert not [row for row in table["devices"] if row["address"].startswith(("10.31.", "172.17."))], (
        "no management address and no bridge off the map")
    devices = [row["device"] for row in table["devices"]]
    assert devices == sorted(devices, key=[node["name"] for node in json.loads(OPENSTACK.read_text())["topology"]["nodes"]].index)
    assert table["services"] == [
        {"name": "board.com", "host": "fsl-waf", "port": 80}, {"name": "corp.com", "host": "fsl-waf", "port": 80},
        {"name": "board-db", "host": "board-db", "port": 3306}, {"name": "corp-db", "host": "corp-db", "port": 3306}]

def test_the_service_ports_are_the_ones_the_waf_and_the_databases_listen_on():
    nginx = (ROOT / "deploy" / "waf" / "range.conf").read_text()
    session = yaml.safe_load((ROOT / "session.yaml").read_text())
    board = yaml.safe_load((ROOT / "wargames" / "board" / "compose.yaml").read_text())

    assert re.findall(r"listen (\d+)", nginx) == [str(topology.SITE_PORT)] * 2
    assert session["services"]["waf"]["environment"]["PORT"] == str(topology.SITE_PORT)
    assert board["services"]["board-db"]["image"].startswith("mysql@")
    assert (ROOT / "wargames" / "corp" / "db" / "Dockerfile").read_text().startswith("FROM mysql@")
    assert topology.DATABASE_PORT == 3306, "MySQL's default port, which neither database changes"

def test_a_slot_s_addressing_table_is_read_once_and_kept_with_its_map(served):
    reads = []

    def read():
        reads.append(1)
        return read_slot()

    first = maps.addresses("slot 2", read)
    maps.publish("slot 2", read)
    again = maps.addresses("slot 2", lambda: [])

    assert first == again and len(reads) == 2
    assert {row["device"] for row in first["devices"]} >= {"fsl-kali", "fsl-edge", "fsl-waf", "board.com", "corp.com"}
    maps.tidy(maps.SLOT, [])
    assert "slot 2" not in maps._found

@pytest.mark.django_db
def test_the_addresses_endpoint_serves_the_session_s_table_and_says_why_when_the_range_cannot(client):
    from tests.sessions import open_session

    session_id = open_session(client)
    table = {"devices": [{"device": "fsl-waf"}], "services": []}
    with patch("api.views._map_key", return_value="slot 1"), patch.object(maps, "addresses", return_value=table):
        found = client.get(f"/api/sessions/{session_id}/topology/addresses/").json()
    with patch("api.views._map_key", return_value="slot 1"), \
         patch.object(maps, "addresses", side_effect=RangeUnavailable("fsl-waf did not answer")):
        refused = client.get(f"/api/sessions/{session_id}/topology/addresses/").json()
    with patch("api.views._map_key", return_value=None):
        none = client.get(f"/api/sessions/{session_id}/topology/addresses/").json()

    assert found == {**table, "detail": ""}
    assert refused == {"devices": [], "services": [], "detail": "fsl-waf did not answer"}
    assert none["devices"] == [] and none["detail"]
    assert client.get("/api/sessions/999999/topology/addresses/").status_code == 404
