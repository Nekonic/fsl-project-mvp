from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from range.ports import Node, Segment, Shape

pytestmark = pytest.mark.django_db

WHEN_INGESTED = Shape(
    segments=(
        Segment(id="estate", name="Application estate", subnet="172.30.0.0/24",
                network="fsl_estate",
                nodes=(Node("fsl-waf", "172.30.0.3"),
                       Node("fsl-juice-shop", "172.30.0.2"))),
    ),
    sensors=(),
)
AFTER_A_RECREATE = Shape(
    segments=(
        Segment(id="estate", name="Application estate", subnet="172.30.0.0/24",
                network="fsl_estate",
                nodes=(Node("fsl-wiki", "172.30.0.3"),
                       Node("fsl-juice-shop", "172.30.0.2"))),
    ),
    sensors=(),
)

def stub(shape):
    class Stub:
        def segments(self):
            return self.describe().segments

        def describe(self):
            return shape

    return patch("api.views.substrate", Stub)

def ingested(client, shape):
    from api.models import Session

    session = Session.objects.create()
    alert = {
        "detection_id": "a1", "source": "suricata",
        "signature": "FSL SQLi attempt - URI", "severity": 2,
        "timestamp": timezone.now(), "src_ip": "172.30.0.3", "marker": None,
        "raw": {"src_ip": "172.30.0.3", "dest_ip": "172.30.0.2", "dest_port": 3000},
    }
    with stub(shape), patch("api.views.elastic.fetch", return_value=([], None)), \
            patch("api.views.elastic.normalize_all", return_value=[alert]):
        client.post_json(f"/api/sessions/{session.id}/ingest/", {})
    return session

def test_the_alert_remembers_who_held_the_address_when_it_was_written(client):
    session = ingested(client, WHEN_INGESTED)

    with stub(AFTER_A_RECREATE):
        top = client.get(f"/api/sessions/{session.id}/top/").json()

    assert top["sources"][0]["host"] == "fsl-waf", (
        "the address was resolved against the range as it is now, not as it "
        "was when the alert was written. Docker hands these out by DHCP, so "
        "after a recreate the dashboard reports whichever container inherited "
        "the address - here it would say the wiki attacked the target"
    )

def test_the_destination_remembers_too(client):
    session = ingested(client, WHEN_INGESTED)

    with stub(AFTER_A_RECREATE):
        top = client.get(f"/api/sessions/{session.id}/top/").json()

    assert top["destinations"][0]["host"] == "fsl-juice-shop"

def test_an_address_nothing_held_gets_no_name_rather_than_a_wrong_one(client):
    from api.models import Session

    session = Session.objects.create()
    alert = {
        "detection_id": "b1", "source": "suricata", "signature": "x",
        "severity": 2, "timestamp": timezone.now(), "src_ip": "10.9.9.9",
        "marker": None, "raw": {"src_ip": "10.9.9.9"},
    }
    with stub(WHEN_INGESTED), patch("api.views.elastic.fetch", return_value=([], None)), \
            patch("api.views.elastic.normalize_all", return_value=[alert]):
        client.post_json(f"/api/sessions/{session.id}/ingest/", {})

    with stub(AFTER_A_RECREATE):
        top = client.get(f"/api/sessions/{session.id}/top/").json()

    assert top["sources"][0]["host"] == ""

def test_the_range_being_unreachable_does_not_lose_the_alert(client):
    from api.models import Session
    from range.ports import RangeUnavailable

    session = Session.objects.create()
    alert = {
        "detection_id": "c1", "source": "suricata", "signature": "x",
        "severity": 2, "timestamp": timezone.now(), "src_ip": "172.30.0.3",
        "marker": None, "raw": {"src_ip": "172.30.0.3"},
    }

    class Gone:
        def segments(self):
            return self.describe().segments

        def describe(self):
            raise RangeUnavailable("docker is not there")

    with patch("api.views.substrate", Gone), \
            patch("api.views.elastic.fetch", return_value=([], None)), \
            patch("api.views.elastic.normalize_all", return_value=[alert]):
        response = client.post_json(f"/api/sessions/{session.id}/ingest/", {})

    assert response.status_code == 200, response.content
    listed = client.get(f"/api/sessions/{session.id}/detections/").json()
    assert len(listed) == 1, "the alert was dropped because the range was down"
