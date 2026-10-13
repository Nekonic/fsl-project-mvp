import json
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.test import override_settings

import gns3
import topology
from range import declared
from range.ports import Node, Segment, Shape
from tests.sessions import OPENED, open_session
from tests.test_topology import EDGE, MGMT, stub

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCKER = ROOT / "deploy" / "topology" / "range-docker.gns3"
OPENSTACK = ROOT / "deploy" / "topology" / "range-openstack.gns3"
DOCKER_KO = ROOT / "deploy" / "topology" / "range-docker.ko.gns3"

def detection(source, src_ip, **raw):
    return SimpleNamespace(source=source, src_ip=src_ip, signature=f"{source} saw it", raw=raw)

def openstack_nodes():
    standing = {
        "fsl-kali": {"internet": ["5.188.10.10", "73.0.0.10"], "mgmt": ["10.31.0.180"]},
        "fsl-edge": {"internet": ["5.188.10.1", "73.0.0.1"], "estate": ["10.30.0.1"], "mgmt": ["10.31.0.215"]},
        "fsl-waf": {"estate": ["10.30.0.102"], "mgmt": ["10.31.0.44"]},
        "fsl-wargame-host": {"estate": ["10.30.0.63"], "mgmt": ["10.31.0.107"]},
        "fsl-platform": {"mgmt": ["10.31.0.238"]},
    }
    return {name: {"status": "running", "addresses": held} for name, held in standing.items()}

def docker_nodes():
    standing = {
        "fsl-kali": {"internet": ["5.188.10.3"]},
        "fsl-proxy": {"internet": ["5.188.10.5"]},
        "fsl-waf": {"internet": ["5.188.10.4"], "estate": ["172.30.0.3"]},
        "fsl-platform": {"internet": ["5.188.10.2"], "estate": ["172.30.0.9"], "mgmt": ["172.31.0.4"]},
        "fsl-wg-board": {"estate": ["172.30.0.2"]},
    }
    return {name: {"status": "running", "addresses": held} for name, held in standing.items()}

def followed(substrate, nodes, sent, seen=(), named=lambda name: name):
    project = OPENSTACK if substrate == "openstack" else DOCKER
    stack = declared.read(flavor=substrate)
    return topology.follow(json.loads(project.read_text()), stack, nodes, sent, list(seen), named)

def walked(found):
    return [hop["node"] for hop in found["hops"]]

def by_node(found):
    return {hop["node"]: hop for hop in found["hops"] if hop["node"]}

def sensed(src_ip, dest_ip, host, sid=9000001, **raw):
    return detection("suricata", src_ip, alert={"signature_id": sid}, dest_ip=dest_ip,
                     log={"syslog": {"hostname": host}}, **raw)

def test_on_openstack_the_website_pane_goes_from_the_platform_over_mgmt_to_the_slot_s_waf():
    sent = {"kind": "browse", "sender": "fsl-platform", "to": "10.31.0.44", "status": 200, "blocked": False}

    found = followed("openstack", openstack_nodes(), sent)

    assert walked(found) == [
        "fsl-platform", "mgmt", "fsl-waf", "estate", "fsl-wargame-host", "board-default", "board",
    ], "the site proxy addresses the WAF's management port, so it never crosses the internet or the edge"
    hops = by_node(found)
    assert found["hops"][0]["source"] == "10.31.0.238", "the platform's own address on the segment it left on"
    assert "fsl-edge" not in hops and "internet" not in hops
    assert hops["fsl-waf"]["verdict"] == "passed" and hops["fsl-waf"]["evidence"] is True
    assert hops["fsl-wargame-host"]["sensor"] == "fsl-wargame-host" and hops["fsl-wargame-host"]["alerts"] == []
    assert hops["fsl-wargame-host"]["evidence"] is False, "a sensor that raised nothing is no record of the request"
    assert hops["board"] == {"node": "board", "kind": "host", "evidence": True, "status": 200, "reached": True}

def test_on_openstack_a_case_leaves_kali_with_its_origin_address_and_the_edge_routes_it_to_the_waf():
    sent = {"kind": "case", "sender": "fsl-kali", "on": "ru", "source": "5.188.10.10", "status": 403}
    seen = [
        sensed("5.188.10.10", "10.30.0.102", "fsl-edge.range.internal", http={"status": 403}),
        detection("modsecurity", "5.188.10.10", details={"ruleId": "942100"}, host_ip="10.30.0.102"),
        detection("modsecurity", "5.188.10.10", details={"ruleId": "949110"}, host_ip="10.30.0.102"),
    ]

    found = followed("openstack", openstack_nodes(), sent, seen)
    hops = by_node(found)

    assert walked(found) == [
        "fsl-kali", "internet", "fsl-edge", "estate", "fsl-waf", "estate", "fsl-wargame-host",
        "board-default", "board",
    ]
    assert found["hops"][0]["source"] == "5.188.10.10"
    assert hops["fsl-edge"]["sensor"] == "fsl-edge"
    assert hops["fsl-edge"]["alerts"] == [{"signature": "suricata saw it", "sid": 9000001}]
    assert hops["fsl-waf"]["verdict"] == "blocked" and hops["fsl-waf"]["rules"] == ["942100", "949110"]
    assert hops["board"]["reached"] is False and hops["board"]["status"] is None

def test_a_case_with_no_alert_reaches_the_waf_by_the_name_the_range_serves_and_says_what_it_did_not_see():
    sent = {"kind": "case", "sender": "fsl-kali", "on": "ru", "source": "", "status": 200}

    found = followed("openstack", openstack_nodes(), sent)
    hops = by_node(found)

    assert walked(found)[:5] == ["fsl-kali", "internet", "fsl-edge", "estate", "fsl-waf"], (
        "board.com names the WAF's estate address on every range host, so the edge is the way to it"
    )
    assert found["hops"][0]["source"] is None, "an origin nobody recorded is unknown, not a guess"
    assert hops["fsl-edge"]["alerts"] == [] and hops["fsl-edge"]["evidence"] is False
    assert hops["fsl-waf"]["verdict"] == "passed"

def test_the_estate_sensor_s_alert_sits_on_the_wargame_host_and_an_unknown_sensor_s_is_kept_apart():
    sent = {"kind": "case", "sender": "fsl-kali", "on": "ru", "source": "5.188.10.10"}
    seen = [
        sensed("5.188.10.10", "10.30.0.63", "fsl-wargame-host-2", sid=7),
        sensed("5.188.10.10", "10.30.0.102", "somewhere-else-2", sid=8),
    ]

    found = followed("openstack", openstack_nodes(), sent, seen, named=lambda name: f"{name}-2")
    hops = by_node(found)

    assert hops["fsl-wargame-host"]["alerts"] == [{"signature": "suricata saw it", "sid": 7}]
    assert hops["fsl-wargame-host"]["evidence"] is True
    assert hops["fsl-edge"]["alerts"] == []
    assert found["elsewhere"] == [{"sensor": None, "signature": "suricata saw it", "sid": 8}]

def test_on_docker_a_website_request_starts_at_the_platform_on_the_segment_it_left_from():
    seen = [detection("modsecurity", "172.30.0.9", details={"ruleId": "920272"})]
    sent = {"kind": "browse", "sender": "fsl-platform", "to": "172.30.0.3", "status": 200, "blocked": False}

    found = followed("", docker_nodes(), sent, seen)

    assert walked(found) == ["fsl-platform", "estate", "fsl-waf", "estate", "fsl-wg-board"]
    waf = found["hops"][2]
    assert waf["verdict"] == "passed" and waf["rules"] == ["920272"]
    assert waf["sensor"] == "fsl-suricata" and waf["alerts"] == [], (
        "on Docker the sensor shares the WAF's namespace, so its alerts sit on the WAF"
    )
    assert found["hops"][-1] == {"node": "fsl-wg-board", "kind": "host", "evidence": True,
                                 "status": 200, "reached": True}

def test_on_docker_a_case_starts_on_its_origin_network_where_the_waf_answers_to_the_name():
    sent = {"kind": "case", "sender": "fsl-kali", "on": "ru", "source": "", "status": 200}
    seen = [detection("suricata", "5.188.10.77", alert={"signature_id": 5}, dest_ip="5.188.10.4")]

    found = followed("", docker_nodes(), sent, seen)

    assert walked(found) == ["fsl-kali", "internet", "fsl-waf", "estate", "fsl-wg-board"], (
        "no edge on Docker: the case box stands on the origin network with the WAF"
    )
    assert found["hops"][0]["source"] == "5.188.10.77", "the sensor saw the address the box really used"
    assert by_node(found)["fsl-waf"]["alerts"] == [{"signature": "suricata saw it", "sid": 5}]

def test_a_website_request_with_no_recorded_address_draws_an_unknown_stretch_rather_than_a_route():
    sent = {"kind": "browse", "sender": "fsl-platform", "to": "", "status": 200, "blocked": False}

    found = followed("openstack", openstack_nodes(), sent)

    assert walked(found)[:3] == ["fsl-platform", None, "fsl-waf"]
    assert found["hops"][1] == {"node": None, "kind": "unknown"}
    assert found["hops"][0]["source"] is None
    assert "fsl-edge" not in by_node(found), "no hop is drawn on a guess"

def test_without_a_gns3_server_the_project_is_the_file_in_the_repo():
    with override_settings(FSL_GNS3_URL=""):
        found = gns3.project()

    assert found["source"] == "file"
    assert found["project"] == json.loads(DOCKER.read_text())
    assert found["web_ui"] is None

def served_by(status, document):
    def reply(url, **kwargs):
        body = {"access_token": "t"} if url.endswith("/authenticate") else (
            document if url.endswith("/gns3file") else {"status": status})
        return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)
    return patch("gns3.requests.post", side_effect=reply), patch("gns3.requests.get", side_effect=reply)

def test_the_web_ui_is_offered_only_while_gns3_holds_the_project_open():
    served = dict(json.loads(DOCKER.read_text()), revision=10)
    with override_settings(FSL_GNS3_URL="http://gns3:3080"):
        post, get = served_by("opened", served)
        with post, get:
            opened = gns3.project()
        post, get = served_by("closed", served)
        with post, get:
            closed = gns3.project()

    assert opened["source"] == "gns3" and opened["project"]["revision"] == 10
    assert opened["web_ui"] == {"port": 3080,
                                "path": f"/static/web-ui/fsl-auditor.html?project={served['project_id']}"}
    assert closed["web_ui"] is None, "GNS3's web UI opens a closed project, which a read-only user may not"

def test_a_gns3_server_that_does_not_answer_falls_back_to_the_file_and_says_why():
    with override_settings(FSL_GNS3_URL="http://gns3:3080"), \
         patch("gns3.requests.post", side_effect=requests.ConnectionError("refused")):
        found = gns3.project()

    assert found["source"] == "file" and "refused" in found["detail"]

@pytest.mark.django_db
def test_the_topology_endpoint_serves_the_substrate_s_project(client):
    with override_settings(FSL_GNS3_URL=""):
        found = client.get("/api/topology/").json()

    assert found["project"]["name"] == "fsl-range-docker"

@pytest.mark.django_db
def test_the_topology_endpoint_serves_the_project_drawn_in_the_language_the_console_asks_for(client):
    with override_settings(FSL_GNS3_URL=""):
        english = client.get("/api/topology/?language=en").json()
        korean = client.get("/api/topology/?language=ko").json()
        refused = client.get("/api/topology/?language=fr")

    assert english["project"] == json.loads(DOCKER.read_text())
    assert korean["project"] == json.loads(DOCKER_KO.read_text())
    assert refused.status_code == 400

def test_the_web_ui_opens_the_project_drawn_in_the_language_asked_for():
    korean = json.loads(DOCKER_KO.read_text())
    with override_settings(FSL_GNS3_URL="http://gns3:3080"):
        post, get = served_by("opened", korean)
        with post, get as fetched:
            found = gns3.project("ko")

    assert {call.args[0].split("/projects/")[1].split("/")[0] for call in fetched.call_args_list} == {
        korean["project_id"]}
    assert found["web_ui"]["path"].endswith(f"?project={korean['project_id']}")

@pytest.mark.django_db
def test_a_session_s_topology_carries_the_project_overlay_from_the_same_range_read(client):
    session_id = open_session(client)

    with stub():
        drawn = client.get(f"/api/sessions/{session_id}/topology/").json()

    assert drawn["project"]["project_id"] == json.loads(DOCKER.read_text())["project_id"]
    assert drawn["project"]["nodes"]["fsl-waf"]["status"] == "running"
    assert drawn["project"]["nodes"]["fsl-wg-board"]["status"] == "not reported"

@pytest.mark.django_db
def test_following_a_website_request_reads_its_record_and_its_detections(client):
    from api import site
    from api.models import Detection, Session

    session_id = open_session(client)
    session = Session.objects.get(pk=session_id)
    record = {"id": 7, "at": OPENED.timestamp(), "method": "GET", "url": "http://board.com/search/?q=x",
              "status": 403, "blocked": True, "ms": 12}
    Detection.objects.create(session=session, detection_id="m1", source="modsecurity",
                             signature="SQLi", timestamp=OPENED, src_ip="5.188.10.3",
                             marker=session.browse_marker, raw={"details": {"ruleId": "949110"}})
    Detection.objects.create(session=session, detection_id="other", source="modsecurity",
                             signature="SQLi", timestamp=OPENED, src_ip="5.188.10.3",
                             marker="someone-else", raw={"details": {"ruleId": "942100"}})

    with stub(), patch.object(site, "kept", return_value=[record]):
        followed = client.get(f"/api/sessions/{session_id}/topology/follow/?request=7").json()
        missing = client.get(f"/api/sessions/{session_id}/topology/follow/?request=8")
        unasked = client.get(f"/api/sessions/{session_id}/topology/follow/")

    assert followed["marker"] == "browse" and followed["detections"] == 1
    assert followed["request"]["status"] == 403
    assert followed["source"] == "fsl-platform", "the Website pane is the platform's site proxy, not Kali"
    waf = next(hop for hop in followed["hops"] if hop["node"] == "fsl-waf")
    assert waf["verdict"] == "blocked" and waf["rules"] == ["949110"]
    assert followed["hops"][-1]["reached"] is False
    assert missing.status_code == 404
    assert unasked.status_code == 400

@pytest.mark.django_db
def test_following_a_fired_case_reads_its_launch_record_and_the_alerts_that_carry_its_id(client):
    from api.models import Case, Detection, Session

    session_id = open_session(client)
    session = Session.objects.get(pk=session_id)
    Case.objects.create(session=session, case_id="c-1", name="board-normal-search", malicious=False,
                        correlation="marker", started_at=OPENED, ended_at=OPENED,
                        meta={"launched_on": "ru", "status": 200})
    Detection.objects.create(session=session, detection_id="s1", source="suricata", signature="seen",
                             timestamp=OPENED, src_ip="5.188.10.77", marker="c-1",
                             raw={"alert": {"signature_id": 5}, "dest_ip": "5.188.10.4"})

    with stub():
        followed = client.get(f"/api/sessions/{session_id}/topology/follow/?case=c-1").json()
        missing = client.get(f"/api/sessions/{session_id}/topology/follow/?case=c-2")

    assert followed["case"] == {"case_id": "c-1", "name": "board-normal-search"}
    assert followed["source"] == "fsl-kali" and followed["detections"] == 1
    assert followed["hops"][0]["source"] == "5.188.10.77"
    assert followed["hops"][-1]["reached"] is True and followed["hops"][-1]["status"] == 200
    assert missing.status_code == 404

def test_the_site_proxy_records_the_address_it_actually_reached_and_nothing_when_it_cannot_tell():
    from api import site

    reached = SimpleNamespace(raw=SimpleNamespace(connection=SimpleNamespace(
        sock=SimpleNamespace(getpeername=lambda: ("10.31.0.44", 80)))))
    closed = SimpleNamespace(raw=SimpleNamespace(connection=SimpleNamespace(sock=None), _fp=SimpleNamespace(
        fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(getpeername=lambda: ("172.30.0.3", 80)))))))

    assert site._peer(reached) == "10.31.0.44"
    assert site._peer(closed) == "172.30.0.3", "a WAF that closes the connection still names its address"
    assert site._peer(SimpleNamespace()) == ""

KOREAN = "/search/?q=%EC%84%9C%EC%9A%B8+%EB%A7%9B%EC%A7%91"

def http_event(marker, url, status, host="fsl-wargame-host"):
    from django.utils import timezone

    return {"fsl_source": "suricata", "event_type": "http", "timestamp": timezone.now().isoformat(),
            "src_ip": "10.30.0.102", "dest_ip": "10.30.0.63", "dest_port": 8000, "log": {"syslog": {"hostname": host}},
            "http": {"url": url, "status": status, "http_method": "GET", "http_user_agent": "Mozilla/5.0",
                     "request_headers": [{"name": "X-FSL-Case", "value": marker}] if marker else []}}

def browsed(url, status, request_id=1):
    import time

    return {"id": request_id, "at": time.time(), "method": "GET", "url": f"http://board.com{url}", "to": "10.31.0.44",
            "status": status, "blocked": status == 403, "ms": 40}

def test_a_sensor_hop_shows_the_http_records_of_a_request_no_rule_alerted_on():
    sent = {"kind": "browse", "sender": "fsl-platform", "to": "10.31.0.44", "status": 200, "blocked": False}
    seen = [http_event("browse-1", KOREAN, 200)]

    def walk(events):
        return {hop["node"]: hop for hop in topology.follow(
            json.loads(OPENSTACK.read_text()), declared.read(flavor="openstack"), openstack_nodes(), sent, [],
            seen=events)["hops"]}

    found, quiet = walk(seen), walk([])

    assert found["fsl-wargame-host"]["requests"] == 1 and found["fsl-wargame-host"]["alerts"] == []
    assert found["fsl-wargame-host"]["evidence"] is True, "the sensor recorded the request though nothing alerted"
    assert found["fsl-wargame-host"]["seen"][0] == {"src_ip": "10.30.0.102", "dest_ip": "10.30.0.63", "dest_port": 8000,
                                                    "method": "GET", "url": KOREAN, "status": 200}
    assert quiet["fsl-wargame-host"]["evidence"] is False

@pytest.mark.django_db
def test_following_a_website_request_reads_the_sensor_s_http_records_by_its_marker_or_its_url(client):
    from datetime import timedelta

    from django.utils import timezone

    from api import site
    from api.models import Session

    session = Session.objects.get(pk=open_session(client))
    Session.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=1))
    events = [http_event(session.browse_marker, KOREAN, 200), http_event("", KOREAN, 200),
              http_event("someone-else", KOREAN, 200)]
    indexed = patch("api.views._fetched", lambda index, start, end, newest_first: (
        [(f"doc-{position}", event) for position, event in enumerate(events)], None))
    with stub(), patch.object(site, "kept", return_value=[browsed(KOREAN, 200, request_id=7)]), indexed:
        shown = client.get(f"/api/sessions/{session.pk}/topology/follow/?request=7").json()

    assert shown["sensed"] == 2, "its own marker, or no marker and the same URL; never another request's"


def test_a_second_slot_s_hosts_are_placed_by_the_names_the_range_reports_them_under():
    stack = declared.read(flavor="openstack")
    described = Shape(segments=(Segment(id="mgmt", name="Management", subnet="10.31.0.0/24", nodes=(
        Node(name="fsl-waf", address="10.31.0.195"), Node(name="fsl-platform", address="10.31.0.238"))),), sensors=())

    drawn = topology.overlay(json.loads(OPENSTACK.read_text()), described, stack, lambda name: f"{name}-2")

    assert drawn["nodes"]["fsl-waf"] == {"status": "running", "addresses": {"mgmt": ["10.31.0.195"]}}, (
        "OpenStack reports a slot's servers by their declared names; the slot suffix is only on the VM's own hostname")

@pytest.mark.django_db
def test_following_a_request_reads_the_waf_s_records_that_arrived_since_the_last_ingest(client):
    from django.utils import timezone

    from api import site
    from api.models import Session

    session = Session.objects.get(pk=open_session(client))
    Session.objects.filter(pk=session.pk).update(started_at=timezone.now())
    record = browsed("/search/?q=%27+OR+1%3D1--", 403, request_id=3)
    audit = {"fsl_source": "modsecurity", "@timestamp": timezone.now().isoformat(), "transaction": {
        "client_ip": "10.31.0.238", "time_stamp": timezone.now().strftime("%a %b %d %H:%M:%S %Y"),
        "request": {"method": "GET", "uri": "/search/?q=%27+OR+1%3D1--", "headers": {"X-FSL-Case": session.browse_marker}},
        "messages": [{"message": "SQL Injection Attack Detected via libinjection", "details": {"ruleId": "942100"}},
                     {"message": "Inbound Anomaly Score Exceeded", "details": {"ruleId": "949110"}}]}}
    arrived = patch("api.views._fetched", lambda index, start, end, newest_first: ([("audit-1", audit)], None))
    with stub(), patch.object(site, "kept", return_value=[record]), arrived:
        shown = client.get(f"/api/sessions/{session.pk}/topology/follow/?request=3").json()

    waf = next(hop for hop in shown["hops"] if hop["node"] == "fsl-waf")
    assert waf["verdict"] == "blocked" and waf["rules"] == ["942100", "949110"], "the rules come with the follow, not later"
