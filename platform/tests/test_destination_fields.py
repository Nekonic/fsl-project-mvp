from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from range.ports import Node, Ran, Segment, Shape

pytestmark = pytest.mark.django_db

SHAPE = Shape(
    segments=(
        Segment(id="edge", name="Internet", origin="Moscow, Russia",
                subnet="5.188.10.0/24", network="fsl_edge", gateway="5.188.10.1",
                nodes=(Node("fsl-waf", "5.188.10.4"),)),
        Segment(id="estate", name="Application estate", subnet="172.30.0.0/24",
                network="fsl_estate", gateway="172.30.0.1",
                nodes=(Node("fsl-waf", "172.30.0.5"),
                       Node("fsl-juice-shop", "172.30.0.2"))),
    ),
    sensors=(),
)

class Stub:
    def describe(self):
        return SHAPE

    def runner(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            return Ran(exit_code=0, output="")

        return run

def ranged():
    from unittest.mock import patch as _p

    class Both:
        def __enter__(self):
            self.ps = [_p("api.views.substrate", Stub),
                       _p("api.reachability.substrate", Stub)]
            for p in self.ps:
                p.start()

        def __exit__(self, *e):
            for p in self.ps:
                p.stop()

    return Both()

def scored(client, hits):
    from api.models import Session

    from api import reachability

    reachability.forget()
    session = Session.objects.create()
    started = timezone.now()
    alerts = [
        {
            "detection_id": f"d{i}", "source": "suricata",
            "signature": "FSL SQLi attempt - URI", "severity": 2,
            "timestamp": started, "src_ip": "5.188.10.2", "marker": None,
            "raw": {"src_ip": "5.188.10.2", "dest_ip": ip, "dest_port": port},
        }
        for i, (ip, port) in enumerate(hits)
    ]
    with ranged(), patch("api.views.elastic.fetch", return_value=([], None)), \
            patch("api.views.elastic.normalize_all", return_value=alerts):
        client.post_json(f"/api/sessions/{session.id}/ingest/", {})
    with ranged():
        return client.get(f"/api/sessions/{session.id}/top/").json()

def test_a_destination_is_an_address_and_a_port_not_a_string(client):
    top = scored(client, [("172.30.0.2", 3000)])

    row = top["destinations"][0]
    assert row["dest_ip"] == "172.30.0.2"
    assert row["dest_port"] == 3000
    assert ":" not in str(row.get("dest_ip")), (
        "the address and the port were pasted into one field, so the table "
        "cannot sort or filter on either and a reader has to parse it"
    )

def test_one_host_on_two_of_its_addresses_is_still_two_rows(client):
    top = scored(client, [("5.188.10.4", 80), ("172.30.0.5", 80)])

    assert len(top["destinations"]) == 2, top["destinations"]
    assert {r["host"] for r in top["destinations"]} == {"fsl-waf"}, (
        "the WAF is one machine on two segments, and both legs are worth "
        "seeing: the outside leg is the attack arriving, the estate leg is it "
        "being forwarded inward"
    )

def test_the_same_address_on_two_ports_stays_two_rows(client):
    top = scored(client, [("172.30.0.2", 3000), ("172.30.0.2", 8080)])

    assert len(top["destinations"]) == 2, (
        "collapsing the port lost the difference between the backend the WAF "
        "forwards to and anything else listening on that host"
    )
    assert {r["dest_port"] for r in top["destinations"]} == {3000, 8080}

def test_a_destination_with_no_port_still_has_an_address(client):
    top = scored(client, [("172.30.0.2", None)])

    row = top["destinations"][0]
    assert row["dest_ip"] == "172.30.0.2"
    assert row["dest_port"] is None
