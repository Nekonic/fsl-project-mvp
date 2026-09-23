from unittest.mock import patch

import pytest

from attacker import AttackerUnavailable
from range.ports import Ran, Shape

pytestmark = pytest.mark.django_db

                                                                              
                                                                        
HOME = [{"id": "edge", "label": "Moscow, Russia", "source_ip": "172.20.0.7", "direct_ip": "172.20.0.7",
         "target_url": "http://5.188.10.9:8080", "subnet": "", "network": "fsl_edge",
         "address": "5.188.10.9", "default": True}]
REFUSED = "sh: can't create /label/origin: Read-only file system"

def refusing(argv, stdin=None, timeout=60.0):
    return Ran(1, REFUSED)

def stub(proxy=None):
    class Stub:
        def segments(self):
            return self.describe().segments

        def describe(self):
            return Shape(segments=(), sensors=())

        def runner(self, role, segment_id=""):
            return proxy

    return patch("api.views.substrate", Stub)

def test_attacker_reports_the_address_alerts_will_carry(client):
    with stub(), patch("api.views.attacker.origins", return_value=HOME):
        response = client.get("/api/attacker/")

    assert response.status_code == 200
    assert response.json()["source_ip"] == "172.20.0.7"
    assert response.json()["terminal_url"]

def test_attacker_that_is_not_running_is_503_not_a_guess(client):
    with stub(), patch(
        "api.views.attacker.origins",
        side_effect=AttackerUnavailable("no such container: fsl-kali"),
    ):
        response = client.get("/api/attacker/")

    assert response.status_code == 503
    assert "fsl-kali" in response.json()["detail"]

@pytest.mark.parametrize("path, body", [
    ("/api/attacker/label/", {"case_id": "c0ffee"}),
    ("/api/attacker/label/", {"case_id": None}),
    ("/api/attacker/origin/", {"origin": "edge"}),
])
def test_a_label_or_origin_the_proxy_did_not_take_is_503_with_its_reason(client, path, body):
    with stub(proxy=refusing), patch("api.views.attacker.origins", return_value=HOME):
        response = client.post_json(path, body)

    assert response.status_code == 503, (
        f"{path} answered {response.status_code} for a write the proxy refused, "
        f"so the console believed the terminal was stamped or moved when it was not"
    )
    assert REFUSED in response.json()["detail"]

def test_a_terminal_window_is_recorded_as_a_window_case(client):
                                                                           
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    created = client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": "44444444-4444-4444-8444-444444444444",
        "name": "manual-sqlmap",
        "malicious": True,
        "correlation": "window",
        "source_ip": "172.20.0.7", "direct_ip": "172.20.0.7",
        "started_at": "2026-09-20T12:00:00Z",
        "ended_at": "2026-09-20T12:02:00Z",
    })

    assert created.status_code == 201
    assert created.json()["correlation"] == "window"
    assert created.json()["source_ip"] == "172.20.0.7"
