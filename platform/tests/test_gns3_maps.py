import io
import json
import pathlib
import threading
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

import gns3
import topology
from api import maps
from range import declared, interfaces, openstack
from range.interfaces import Interface
from range.ports import Node, Ran, RangeUnavailable, Segment, Shape
from tests.test_gns3_topology import learner_of

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "deploy" / "topology"
OPENSTACK = TOPOLOGY / "range-openstack.gns3"
LABEL_KEYS = {"text", "style", "x", "y", "rotation"}
DEFAULT_ORIGIN = "5.188.10.0/24"
PLATFORM_NIC = Interface("fsl-platform", "ens7", "10.31.0.238/24", "mgmt")

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
    adapter.declared = declared.read()
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


def slot_map(number=2, path=OPENSTACK, found=None, wargame="board"):
    found = found if found is not None else read_slot()
    return topology.labelled(json.loads(path.read_text()), learner_of(declared.read(), wargame), found,
                             f"slot-{number}-{wargame}", f"slot {number} {wargame}")

def labels(document):
    by_id = {node["node_id"]: node for node in document["topology"]["nodes"]}
    shown = {}
    for link in document["topology"]["links"]:
        one, other = (by_id[end["node_id"]] for end in link["nodes"])
        shown[(one["name"], other["name"])] = link["nodes"][0]["label"]
        shown[(other["name"], one["name"])] = link["nodes"][1]["label"]
    return shown


def test_no_management_address_reaches_the_learner_map():
    shown = {pair: label["text"] for pair, label in labels(slot_map(2, OPENSTACK, read_slot() + [PLATFORM_NIC])).items()}

    assert [text for text in shown.values() if text], "the map is labelled at all"
    assert not [text for text in shown.values() if "10.31.0." in text]

def test_each_slot_s_map_carries_its_own_addresses_and_ids_and_keeps_every_drawing_of_its_wargame():
    drawn = json.loads(OPENSTACK.read_text())
    template = topology.for_wargame(drawn, learner_of(declared.read(), "board"))
    one = slot_map(1, found=[Interface("fsl-waf", "ens3", "10.30.0.102/24", "estate")])
    two = slot_map(2)
    ids = lambda document: ({document["project_id"]} | {n["node_id"] for n in document["topology"]["nodes"]}
                            | {link["link_id"] for link in document["topology"]["links"]}
                            | {d["drawing_id"] for d in document["topology"]["drawings"]})

    assert labels(one)[("waf", "sw1")]["text"] == "ens3 10.30.0.102/24"
    assert labels(two)[("waf", "sw1")]["text"] == "ens3 10.30.0.177/24"
    assert not ids(one) & ids(two) and not ids(one) & ids(drawn) and not ids(two) & ids(drawn)
    assert two["project_id"] == str(uuid.uuid5(uuid.UUID(drawn["project_id"]), "slot-2-board"))
    assert one["name"] == "range-openstack slot 1 board" and two["show_interface_labels"] is True
    assert [d["svg"] for d in two["topology"]["drawings"] if "<rect" in d["svg"]] == [
        d["svg"] for d in template["topology"]["drawings"] if "<rect" in d["svg"]]
    assert [(n["name"], n["symbol"], n["x"], n["y"]) for n in two["topology"]["nodes"]] == [
        (n["name"], n["symbol"], n["x"], n["y"]) for n in template["topology"]["nodes"]]

def test_a_generated_map_is_a_gns3_2_2_project_whose_labels_fit_both_releases_schemas():
    document = slot_map(2)
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
    settings.RANGE = declared.read()
    fake = Served()
    for name in ("publish", "status", "remove_except"):
        monkeypatch.setattr(gns3, name, getattr(fake, name))
    maps._loaded.clear()
    return fake

def test_a_slot_s_map_is_loaded_once_and_not_again_while_nothing_changed(served):
    maps.publish("slot 2 board", read_slot)
    maps.publish("slot 2 board", read_slot)

    assert [document["name"] for document in served.published] == ["range-openstack slot 2 board"]
    assert [document["project_id"] for document in served.published] == [maps.project_id("slot 2 board")]

def test_a_session_s_map_is_drawn_for_the_wargame_it_defends(served):
    maps.publish("slot 1 corp", read_slot)
    names = {node["name"] for node in served.published[0]["topology"]["nodes"]}

    assert {"corp.com", "corp-db", "sw2"} <= names and not {"board.com", "board-db"} & names
    assert "customers" not in names, "corp declares no customers"
    assert maps.wargame_of("slot 1 corp") == "corp" and maps.learner("corp").hosts["fsl-kali"] == ("kali",)
    assert maps.learner("board").hosts["fsl-kali"] == ("kali", "customers"), (
        "on OpenStack the customers' program runs on the attacker's box")

def test_a_changed_address_loads_the_slot_s_maps_again(served):
    maps.publish("slot 2 board", read_slot)
    maps.publish("slot 2 board", lambda: [Interface("fsl-waf", "ens3", "10.30.0.99/24", "estate")])

    assert len(served.published) == 2
    assert labels(served.published[-1])[("waf", "sw1")]["text"] == "ens3 10.30.0.99/24"

def test_tidying_keeps_only_the_maps_of_the_slots_still_standing(served):
    maps.tidy(maps.SLOT, ["slot 2 board"])

    assert served.removed == [("range-openstack slot ", [maps.project_id("slot 2 board")])], (
        "a canonical map never matches the prefix"
    )

def test_the_map_served_for_a_session_is_its_slot_s_project_once_gns3_holds_it_open(served, monkeypatch):
    monkeypatch.setattr(gns3, "project", lambda kept=None: {"project_id": (kept or {}).get("project_id")})

    shown = maps.served("slot 2 board", read_slot)

    assert shown["project_id"] == maps.project_id("slot 2 board")
    assert len(served.published) == 1, "a map GNS3 did not hold yet is loaded before it is served"

def test_a_map_request_waits_for_the_slot_s_load_in_flight_and_is_served_the_map_it_loaded(served, monkeypatch):
    monkeypatch.setattr(gns3, "project", lambda kept=None: {"project_id": (kept or {}).get("project_id")})
    key = "slot 2 board"
    served.opened = {maps.project_id(key)}
    reading, answered, shown = threading.Event(), threading.Event(), {}

    def slow_read():
        reading.set()
        answered.wait(5)
        return read_slot()

    def again():
        raise AssertionError("the slot's hosts were read again over SSH")

    loading = maps.begin(key, slow_read, maps.SLOT, [key])
    reading.wait(5)
    asking = threading.Thread(target=lambda: shown.update(maps.served(key, again)))
    asking.start()
    asking.join(0.3)
    waited = asking.is_alive() and not shown
    answered.set()
    loading.join(5)
    asking.join(5)

    assert waited, "a map GNS3 still holds open from before is not shown while the session's own load replaces it"
    assert shown["project_id"] == maps.project_id(key)
    assert [document["name"] for document in served.published] == ["range-openstack slot 2 board"]

def test_a_read_some_host_did_not_answer_loads_no_map_and_a_check_still_reads_the_hosts_that_did(served, monkeypatch):
    from api import views

    adapter, _ = slot_adapter({"attacker": KALI_IP, "gateway": WAF_IP, "wargames": HOST_IP})
    adapter._own_listed = lambda: ""
    monkeypatch.setattr(views, "_range", lambda session=None, **_: adapter)
    session = SimpleNamespace(pk=0, scenario="board", ended_at="ended")

    maps.begin("slot 1 board", views._map_read(session, skip_unanswered=False), maps.SLOT, ["slot 1 board"]).join(5)

    assert served.published == [], "a map without the firewall's interfaces would be loaded again once it answers"
    assert "edge did not answer" in maps._failed.pop("slot 1 board")
    assert "fsl-kali" in {one.host for one in views._map_read(session)()}

def test_a_host_that_does_not_answer_fails_a_read_that_asks_every_host():
    adapter, _ = slot_adapter({"attacker": KALI_IP, "gateway": WAF_IP, "wargames": HOST_IP})

    with pytest.raises(RangeUnavailable, match="edge did not answer"):
        adapter.interfaces(skip_unanswered=False)

def test_a_map_that_cannot_be_loaded_falls_back_to_the_range_s_own_map_and_says_why(served, monkeypatch):
    def refused(document):
        raise gns3.Unavailable("GNS3 refused the admin sign-in")

    monkeypatch.setattr(gns3, "publish", refused)
    monkeypatch.setattr(gns3, "project", lambda kept=None: {
        "project_id": "canonical", "detail": "", "nodes": {node["name"] for node in kept["topology"]["nodes"]}})

    shown = maps.served("slot 1 board", read_slot)

    assert shown["project_id"] == "canonical" and "admin sign-in" in shown["detail"]
    assert "board.com" in shown["nodes"] and "corp.com" not in shown["nodes"], "the fallback is the wargame's own map"

def test_publishing_replaces_the_project_by_import_opens_it_as_admin_and_starts_its_nodes(settings, tmp_path):
    settings.FSL_GNS3_URL = "http://gns3:3080"
    settings.FSL_GNS3_ADMIN_PASSWORD = ""
    secret = tmp_path / "admin-password"
    secret.write_text("s3cret\n")
    settings.FSL_GNS3_ADMIN_PASSWORD_FILE = secret
    document = slot_map(2)
    calls = []
    project_id = document["project_id"]

    def answer(method):
        def reply(url, **kwargs):
            calls.append((method, url.split("/v3")[1], kwargs))
            body = {"access_token": "t"} if url.endswith("/authenticate") else {"status": "opened"}
            if method == "get":
                body = [{"project_id": project_id, "status": "opened"}]
            return SimpleNamespace(status_code=200, json=lambda: body, raise_for_status=lambda: None)
        return reply

    with patch("gns3.requests.post", side_effect=answer("post")), \
         patch("gns3.requests.get", side_effect=answer("get")), \
         patch("gns3.requests.put", side_effect=answer("put")), \
         patch("gns3.requests.delete", side_effect=answer("delete")):
        assert gns3.publish(document) == "opened"

    assert [(method, path) for method, path, _ in calls] == [
        ("post", "/access/users/authenticate"), ("get", "/projects"), ("delete", f"/projects/{project_id}"),
        ("post", f"/projects/{project_id}/import"), ("put", f"/projects/{project_id}"),
        ("post", f"/projects/{project_id}/open"), ("post", f"/projects/{project_id}/nodes/start")], (
        "every node is started, so GNS3 draws each link end green; the display containers only idle")
    assert calls[4][2]["json"] == {"auto_close": False}, (
        "an import is made with auto_close on whatever the file says, and a project closed when the last web "
        "client left stops its nodes")
    assert calls[0][2]["json"] == {"username": "admin", "password": "s3cret"}
    archive = zipfile.ZipFile(io.BytesIO(calls[3][2]["data"]))
    assert json.loads(archive.read("project.gns3")) == document, (
        "an import whose project.gns3 keeps the URL's project id keeps every id, as GNS3 restores a snapshot"
    )


def test_a_project_gns3_does_not_hold_is_imported_without_a_delete(settings):
    settings.FSL_GNS3_URL = "http://gns3:3080"
    settings.FSL_GNS3_ADMIN_PASSWORD = "s3cret"
    listed = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [{"project_id": "another"}])
    answered = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"status": "opened"})

    with patch("gns3._signed", return_value={}), \
         patch("gns3.requests.get", return_value=listed), \
         patch("gns3.requests.post", return_value=answered), \
         patch("gns3.requests.put", return_value=answered), \
         patch("gns3.requests.delete") as deleted:
        gns3.publish(slot_map(1))

    assert not deleted.called, (
        "GNS3 logs every 404 at ERROR, so a DELETE of a project it never held wrote one error per first load"
    )

@pytest.mark.django_db
def test_the_topology_endpoint_serves_the_session_s_own_map_when_gns3_runs(client):
    from tests.sessions import open_session

    session_id = open_session(client)
    with override_settings(FSL_GNS3_URL="http://gns3:3080"), \
         patch("api.views._map_key", return_value="slot 1 board"), \
         patch.object(maps, "served", return_value={"project": {"name": "mine"}, "web_ui": None}) as asked:
        found = client.get(f"/api/topology/?session={session_id}").json()
        refused = client.get("/api/topology/?session=x")

    assert found["project"] == {"name": "mine"}
    assert asked.call_args.args[0] == "slot 1 board"
    assert refused.status_code == 400


@pytest.mark.django_db
def test_a_slot_keeps_the_map_of_its_newest_session():
    from django.utils import timezone

    from api.models import Session
    from api.views import _maps_live

    slotted = SimpleNamespace(slots=2, in_slot=lambda number: None)
    Session.objects.create(scenario="board")
    Session.objects.create(scenario="board", slot=1, ended_at=timezone.now())
    Session.objects.create(scenario="corp", slot=1)
    Session.objects.create(scenario="board", slot=2, ended_at=timezone.now())

    assert _maps_live(slotted) == ["slot 1 corp", "slot 2 board"], "one wargame's map per slot, the newest session's"


@pytest.mark.django_db
def test_at_start_the_platform_loads_the_map_of_each_slot_s_newest_session(settings):
    from api import views
    from api.models import Session

    settings.FSL_GNS3_URL = "http://gns3:3080"
    cloud = SimpleNamespace(slots=2, interfaces=None, in_slot=lambda number: SimpleNamespace(
        slots=2, interfaces=None, in_slot=None, number=number))
    Session.objects.create(scenario="board", slot=1)
    Session.objects.create(scenario="corp", slot=2)
    maps._loaded.clear()
    with patch("api.views.substrate", lambda: cloud), patch.object(maps, "begin", side_effect=loads()) as begun:
        views.publish_maps(pause=refuse_to_wait)

    assert [(call.args[0], call.args[3]) for call in begun.call_args_list] == [
        ("slot 1 board", ["slot 1 board", "slot 2 corp"]), ("slot 2 corp", ["slot 1 board", "slot 2 corp"])]

def refuse_to_wait(seconds):
    raise AssertionError("the start publish waited although every map loaded")

def loads(failing=()):
    tries = {}

    def begin(key, read, kind, live):
        tries[key] = tries.get(key, 0) + 1
        if tries[key] <= dict(failing).get(key, 0):
            maps._failed[key] = "edge did not answer"
        else:
            maps._loaded[key] = "fingerprint"
        return None
    return begin

def slotted_cloud():
    return SimpleNamespace(slots=2, interfaces=None, in_slot=lambda number: SimpleNamespace(
        slots=2, interfaces=None, in_slot=None, number=number))

@pytest.mark.django_db
def test_a_cloud_that_does_not_answer_at_start_is_asked_again_a_bounded_number_of_times(settings, caplog):
    from api import views

    def unanswered():
        raise RangeUnavailable("keystone did not answer")

    settings.FSL_GNS3_URL = "http://gns3:3080"
    waits = []
    with patch("api.views.substrate", unanswered), patch.object(maps, "begin") as begun:
        views.publish_maps(pause=waits.append)

    assert not begun.called and "keystone did not answer" in caplog.text
    assert waits == [views.MAP_START_RETRY_SECONDS] * (views.MAP_START_ATTEMPTS - 1)
    assert "each loads when its session asks" in caplog.text

@pytest.mark.django_db
def test_a_slot_whose_hosts_did_not_all_answer_at_start_is_read_again_and_its_map_loads(served, settings, monkeypatch):
    from api import views
    from api.models import Session

    settings.FSL_GNS3_URL = "http://gns3:3080"
    Session.objects.create(scenario="board", slot=1)
    rebooting, _ = slot_adapter({"attacker": KALI_IP, "gateway": WAF_IP, "wargames": HOST_IP})
    answering, _ = slot_adapter()
    rebooting._own_listed = answering._own_listed = lambda: ""
    reads = iter([rebooting, answering])
    monkeypatch.setattr(views, "_range", lambda session=None, **_: next(reads))
    waits = []
    with patch("api.views.substrate", slotted_cloud):
        views.publish_maps(pause=waits.append)

    assert waits == [views.MAP_START_RETRY_SECONDS], "the edge rebooting at start fails the first read only"
    assert [document["name"] for document in served.published] == ["range-openstack slot 1 board"]
    assert maps.loaded("slot 1 board")

@pytest.mark.django_db
def test_a_slot_whose_map_loaded_is_not_read_again_while_another_slot_is_retried(settings):
    from api import views
    from api.models import Session

    settings.FSL_GNS3_URL = "http://gns3:3080"
    Session.objects.create(scenario="board", slot=1)
    Session.objects.create(scenario="corp", slot=2)
    maps._loaded.clear()
    waits = []
    with patch("api.views.substrate", slotted_cloud), patch.object(
            maps, "begin", side_effect=loads(failing={"slot 2 corp": 2})) as begun:
        views.publish_maps(pause=waits.append)

    assert [call.args[0] for call in begun.call_args_list] == [
        "slot 1 board", "slot 2 corp", "slot 2 corp", "slot 2 corp"]
    assert len(waits) == 2

@pytest.mark.django_db
def test_a_slot_whose_session_loaded_its_map_while_the_start_publish_waited_is_not_loaded_again(settings):
    from api import views
    from api.models import Session

    settings.FSL_GNS3_URL = "http://gns3:3080"
    Session.objects.create(scenario="board", slot=1)
    maps._loaded.clear()
    waits = []

    def session_loads_meanwhile(seconds):
        waits.append(seconds)
        maps._loaded["slot 1 board"] = "loaded by the session's own request"

    with patch("api.views.substrate", slotted_cloud), patch.object(maps, "begin", return_value=None) as begun:
        views.publish_maps(pause=session_loads_meanwhile)

    assert begun.call_count == 1, "a load already in flight is left to finish, and its map is not loaded twice"
    assert waits == [views.MAP_START_RETRY_SECONDS]

def test_the_platform_loads_the_slot_maps_in_the_background_as_it_starts():
    started = (ROOT / "platform" / "fsl" / "wsgi.py").read_text()

    assert 'threading.Thread(target=publish_maps, name="fsl-maps-publish", daemon=True).start()' in started
    assert "views.publish_maps()" in started
