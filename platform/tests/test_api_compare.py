"""Scoring the same traffic by both strategies, and the label that allows it.

A terminal window carries a marker (the proxy stamps it) and sits in a time
window from a known address. That is the only traffic in the project that both
strategies can score, so it is the only place they can be compared.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

WINDOW_CASE = {
    "case_id": "55555555-5555-4555-8555-555555555555",
    "name": "terminal-attack",
    "malicious": True,
    "correlation": "window",
    "source_ip": "172.20.0.7",
    "started_at": "2026-09-20T12:00:00Z",
    "ended_at": "2026-09-20T12:01:00Z",
}


@pytest.fixture
def scored_session(client):
    """One case that both strategies can see, and one alert that fits both."""
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{session_id}/cases/", WINDOW_CASE)

    alert = (
        "es1",
        {
            "fsl_source": "suricata",
            "event_type": "alert",
            "timestamp": "2026-09-20T12:00:30Z",
            "src_ip": "172.20.0.7",
            "alert": {"signature": "SQLi", "severity": 1},
            "http": {
                "request_headers": [
                    {"name": "X-FSL-Case", "value": WINDOW_CASE["case_id"]}
                ]
            },
        },
    )
    with patch("api.views.elastic.fetch", return_value=[alert]):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return session_id


def test_setting_a_label_tells_the_proxy_what_to_stamp(client):
    with patch("api.views.attacker.set_label") as labelled:
        response = client.post_json("/api/attacker/label/", {"case_id": "abc-123"})

    assert response.status_code == 200
    labelled.assert_called_once_with("abc-123")


def test_clearing_the_label_stops_the_stamping(client):
    with patch("api.views.attacker.set_label") as labelled:
        response = client.post_json("/api/attacker/label/", {"case_id": None})

    assert response.status_code == 200
    labelled.assert_called_once_with(None)


def test_by_default_a_case_is_scored_by_the_strategy_it_declares(client, scored_session):
    scored = client.get(f"/api/sessions/{scored_session}/score/").json()

    assert scored["tp"] == 1
    assert scored["per_case"][0]["verdict"] == "TP"


def test_the_strategy_can_be_forced_for_comparison(client, scored_session):
    by_marker = client.get(
        f"/api/sessions/{scored_session}/score/?correlation=marker"
    ).json()
    by_window = client.get(
        f"/api/sessions/{scored_session}/score/?correlation=window"
    ).json()

    # Same traffic, same case, both strategies find it. That agreement is the
    # result; a disagreement would be the interesting one.
    assert by_marker["tp"] == 1
    assert by_window["tp"] == 1


def test_forcing_marker_on_traffic_that_carries_none_misses_it(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{session_id}/cases/", WINDOW_CASE)

    unmarked = (
        "es2",
        {
            "fsl_source": "suricata",
            "event_type": "alert",
            "timestamp": "2026-09-20T12:00:30Z",
            "src_ip": "172.20.0.7",
            "alert": {"signature": "SQLi", "severity": 1},
        },
    )
    with patch("api.views.elastic.fetch", return_value=[unmarked]):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

    by_window = client.get(f"/api/sessions/{session_id}/score/?correlation=window").json()
    by_marker = client.get(f"/api/sessions/{session_id}/score/?correlation=marker").json()

    # This is the comparison earning its keep: the window sees an attack the
    # marker cannot, because nothing labelled the traffic.
    assert by_window["tp"] == 1
    assert by_marker["fn"] == 1


def test_an_unknown_forced_strategy_is_rejected(client, scored_session):
    response = client.get(f"/api/sessions/{scored_session}/score/?correlation=vibes")

    assert response.status_code == 400
    assert "vibes" in response.json()["detail"]
