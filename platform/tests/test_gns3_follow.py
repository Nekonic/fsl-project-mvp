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

def detection(source, src_ip, **raw):
    return SimpleNamespace(source=source, src_ip=src_ip, signature=f"{source} saw it", raw=raw)

def openstack_nodes():
    return {"fsl-edge": {"status": "running", "addresses": {"internet": ["5.188.10.1"]}}}

def test_the_overlay_marks_a_node_the_range_reports_and_one_it_does_not():
    estate = Segment(id="estate", name="", origin="", subnet="172.30.0.0/24",
                     nodes=(Node("fsl-waf", "172.30.0.3"), Node("fsl-wg-board", "172.30.0.2")))
    described = Shape(segments=(EDGE, estate, MGMT), sensors=())

    drawn = topology.overlay(json.loads(DOCKER.read_text()), described, declared.read())

    assert drawn["nodes"]["fsl-waf"] == {
        "status": "running", "addresses": {"internet": ["5.188.10.4"], "estate": ["172.30.0.3"]},
    }, "an origin network is drawn as the internet segment it belongs to"
    assert drawn["nodes"]["fsl-kali"] == {"status": "not reported", "addresses": {}}
    assert "internet" not in drawn["nodes"], "a segment is a switch, not a host"

def test_on_openstack_a_request_crosses_the_edge_the_waf_and_the_wargame_host_to_the_board():
    stack = declared.read(flavor="openstack")
    seen = [
        detection("suricata", "5.188.10.9", alert={"signature_id": 9000001}, http={"status": 403}),
        detection("modsecurity", "5.188.10.9", details={"ruleId": "942100"}),
        detection("modsecurity", "5.188.10.9", details={"ruleId": "949110"}),
    ]

    followed = topology.follow(json.loads(OPENSTACK.read_text()), stack, openstack_nodes(), seen)
    hops = {hop["node"]: hop for hop in followed["hops"]}

    assert [hop["node"] for hop in followed["hops"]] == [
        "internet", "fsl-edge", "estate", "fsl-waf", "estate", "fsl-wargame-host",
        "board-default", "board",
    ], "the edge routes to the estate, and the WAF stands on the estate in front of the target"
    assert followed["hops"][0]["source"] == "5.188.10.9"
    assert hops["fsl-edge"]["alerts"] == [{"signature": "suricata saw it", "sid": 9000001}]
    assert hops["fsl-waf"]["verdict"] == "blocked"
    assert hops["fsl-waf"]["rules"] == ["942100", "949110"]
    assert hops["board"]["reached"] is False and hops["board"]["status"] is None

def test_on_docker_a_website_request_starts_at_the_platform_on_the_segment_it_left_from():
    nodes = {"fsl-platform": {"status": "running", "addresses": {"estate": ["172.30.0.9"]}}}
    seen = [detection("modsecurity", "172.30.0.9", details={"ruleId": "920272"})]
    record = {"status": 200, "blocked": False}

    followed = topology.follow(json.loads(DOCKER.read_text()), declared.read(), nodes, seen, record)

    assert [hop["node"] for hop in followed["hops"]] == [
        "fsl-platform", "estate", "fsl-waf", "estate", "fsl-wg-board",
    ]
    waf = followed["hops"][2]
    assert waf["verdict"] == "passed" and waf["rules"] == ["920272"]
    assert waf["alerts"] == [], "on Docker the sensor shares the WAF's namespace, so its alerts sit on the WAF"
    assert followed["hops"][-1] == {"node": "fsl-wg-board", "kind": "host", "status": 200, "reached": True}

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
    assert [hop["node"] for hop in followed["hops"]][:2] == ["fsl-proxy", "internet"]
    waf = next(hop for hop in followed["hops"] if hop["node"] == "fsl-waf")
    assert waf["verdict"] == "blocked" and waf["rules"] == ["949110"]
    assert followed["hops"][-1]["reached"] is False
    assert missing.status_code == 404
    assert unasked.status_code == 400
