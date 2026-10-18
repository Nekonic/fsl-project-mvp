import pathlib
from dataclasses import replace
from unittest.mock import patch

import pytest

import topology
from range.ports import Node, RangeUnavailable, Segment, Sensor, Shape

from tests.sessions import open_session

EDGE = Segment(
    id="ru", name="Internet", origin="Russia",
    subnet="5.188.10.0/24", network="fsl_edge", gateway="5.188.10.1",
    nodes=(Node("fsl-waf", "5.188.10.4"), Node("fsl-proxy", "5.188.10.3")),
)
ESTATE = Segment(
    id="estate", name="Application estate", origin="",
    subnet="172.30.0.0/24", network="fsl_estate", gateway="172.30.0.1",
    nodes=(Node("fsl-waf", "172.30.0.3"), Node("fsl-juice-shop", "172.30.0.2")),
)
MGMT = Segment(
    id="mgmt", name="", origin="",
    subnet="172.31.0.0/24", network="fsl_mgmt", gateway="172.31.0.1",
    nodes=(Node("fsl-elasticsearch", "172.31.0.2"),),
)

SHAPE = Shape(
    segments=(EDGE, ESTATE, MGMT),
    sensors=(Sensor(name="fsl-suricata", watches="fsl-waf"),),
)

def stub(described=SHAPE, error=None):
    class Stub:
        def segments(self):
            return self.describe().segments

        def describe(self):
            if error is not None:
                raise error
            return described

    return patch("api.views.substrate", Stub)


def segment(found, segment_id):
    return next(s for s in found["segments"] if s["id"] == segment_id)


def test_drawing_the_picture_never_names_the_substrate():
    source = pathlib.Path(topology.__file__).read_text()

    assert "docker" not in source.lower(), (
        "the picture is shaped from what the substrate reported, and would "
        "have to be rewritten for a substrate that is not Docker"
    )
    assert "subprocess" not in source, "shaping the picture is not a round trip"

pytestmark = pytest.mark.django_db


def test_an_alert_with_no_source_is_unplaced_and_a_segment_with_no_subnet_says_zero(client):
    from api.models import Detection
    from tests.sessions import OPENED

    session_id = open_session(client)
    Detection.objects.create(
        session_id=session_id, detection_id="no-source", source="suricata",
        signature="FSL SQLi attempt", timestamp=OPENED, src_ip=None,
    )
    unsized = Shape(segments=(EDGE, replace(MGMT, subnet="")), sensors=SHAPE.sensors)

    with stub(unsized):
        drawn = client.get(f"/api/sessions/{session_id}/topology/").json()

    assert drawn["unplaced"] == 1
    assert segment(drawn, "mgmt")["alerts"] == 0


def _addressed(doc_id, src_ip, dest_ip, dest_port=80):
    return (doc_id, {
        "event": {"module": "suricata"}, "event_type": "alert",
        "timestamp": "2026-09-20T12:00:00Z",
        "src_ip": src_ip, "dest_ip": dest_ip, "dest_port": dest_port,
        "alert": {"signature": "FSL SQLi attempt", "severity": 1},
    })


def test_a_stack_that_cannot_be_read_still_reports_the_addresses_and_guesses_no_host(client):
    session_id = open_session(client)
    with patch("api.views.elastic.fetch",
               return_value=([_addressed("a", "5.188.10.3", "5.188.10.4")], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

    with stub(error=RangeUnavailable("no daemon")):
        found = client.get(f"/api/sessions/{session_id}/top/").json()

    assert [s["src_ip"] for s in found["sources"]] == ["5.188.10.3"]
    assert found["sources"][0]["zone"] == "" and found["sources"][0]["host"] == ""
    assert found["destinations"][0]["host"] == ""


def _alerts_ingested(client, *sources):
    session_id = open_session(client)
    documents = [_addressed(str(index), src_ip, "5.188.10.4") for index, src_ip in enumerate(sources)]
    with stub(), patch("api.views.elastic.fetch", return_value=(documents, None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return session_id


def test_each_alert_lands_on_the_segment_it_arrived_on_and_none_is_dropped(client):
    session_id = _alerts_ingested(client, "5.188.10.3", "5.188.10.5", "172.30.0.3", "10.9.9.9")

    with stub():
        drawn = client.get(f"/api/sessions/{session_id}/topology/").json()

    assert {s["id"]: (s["alerts"], s["outside"]) for s in drawn["segments"]} == {
        "ru": (2, True), "estate": (1, False), "mgmt": (0, False)}
    assert drawn["unplaced"] == 1


def test_every_alert_is_counted_against_exactly_one_address_named_by_its_zone(client):
    session_id = _alerts_ingested(client, "5.188.10.3", "5.188.10.3", "172.30.0.2", "10.9.9.9")

    with stub():
        counted = {s["src_ip"]: s for s in client.get(f"/api/sessions/{session_id}/top/").json()["sources"]}

    assert sum(s["alerts"] for s in counted.values()) == 4
    assert {ip: (s["zone"], s["outside"]) for ip, s in counted.items()} == {
        "5.188.10.3": ("Internet", True), "172.30.0.2": ("Application estate", False), "10.9.9.9": ("", False)}


def test_the_picture_names_hosts_as_the_map_does_and_the_sensor_host_likewise(client):
    session_id = open_session(client)

    with stub():
        drawn = client.get(f"/api/sessions/{session_id}/topology/").json()

    names = {node["name"] for s in drawn["segments"] for node in s["nodes"]}
    names |= {sensor["name"] for sensor in drawn["sensors"]} | {sensor["watches"] for sensor in drawn["sensors"]}
    assert "waf" in names and "log-server" in names
    assert not {name for name in names if name.startswith("fsl-") and name not in ("fsl-juice-shop", "fsl-proxy")}, names
