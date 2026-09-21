"""Where free-form traffic comes from.

Window correlation matches alerts by source IP, so a terminal session can only
be labelled if the console knows the address Suricata will see. Only Docker can
answer that, and if it cannot, saying so is better than labelling a case with
an address that matches nothing.
"""

from unittest.mock import patch

import pytest

from attacker import AttackerUnavailable

pytestmark = pytest.mark.django_db


# The attacker can leave by several places now, so the address is asked of the
# origin rather than of the container. See test_origins.py for the rest.
HOME = [{"id": "edge", "label": "Moscow, Russia", "source_ip": "172.20.0.7", "direct_ip": "172.20.0.7",
         "target_url": "http://waf-edge:8080", "subnet": "", "network": "fsl_edge",
         "default": True}]


def test_attacker_reports_the_address_alerts_will_carry(client):
    with patch("api.views.attacker.origins", return_value=HOME):
        response = client.get("/api/attacker/")

    assert response.status_code == 200
    assert response.json()["source_ip"] == "172.20.0.7"
    assert response.json()["terminal_url"]


def test_attacker_that_is_not_running_is_503_not_a_guess(client):
    with patch(
        "api.views.attacker.origins",
        side_effect=AttackerUnavailable("no such container: fsl-kali"),
    ):
        response = client.get("/api/attacker/")

    assert response.status_code == 503
    assert "fsl-kali" in response.json()["detail"]


def test_a_terminal_window_is_recorded_as_a_window_case(client):
    # The labelled terminal needs no new endpoint: this is the whole of it.
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
