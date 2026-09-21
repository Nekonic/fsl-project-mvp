from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

T0 = "2026-09-20T12:00:00Z"

def alert(doc_id, signature="SQLi"):
    return (
        doc_id,
        {
            "fsl_source": "suricata",
            "event_type": "alert",
            "timestamp": T0,
            "src_ip": "172.20.0.7",
            "alert": {"signature": signature, "severity": 1},
        },
    )

@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]

def ingest(client, session_id, documents):
    with patch("api.views.elastic.fetch", return_value=(documents, None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

def test_after_returns_only_what_the_console_has_not_seen(client, session_id):
    ingest(client, session_id, [alert("a"), alert("b")])
    seen = client.get(f"/api/sessions/{session_id}/detections/").json()
    assert len(seen) == 2

    ingest(client, session_id, [alert("a"), alert("b"), alert("c")])
    new = client.get(
        f"/api/sessions/{session_id}/detections/?after={seen[-1]['id']}"
    ).json()

    assert [d["detection_id"] for d in new] == ["c"]

def test_after_the_latest_row_returns_nothing(client, session_id):
    ingest(client, session_id, [alert("a")])
    seen = client.get(f"/api/sessions/{session_id}/detections/").json()

    assert client.get(
        f"/api/sessions/{session_id}/detections/?after={seen[-1]['id']}"
    ).json() == []

def test_a_nonsense_after_is_rejected_rather_than_ignored(client, session_id):
                                                                          
    response = client.get(f"/api/sessions/{session_id}/detections/?after=soon")

    assert response.status_code == 400
    assert "after" in response.json()["detail"]

def test_one_alert_carries_the_whole_log_behind_it(client, session_id):
    ingest(client, session_id, [alert("a", signature="path traversal")])
    listed = client.get(f"/api/sessions/{session_id}/detections/").json()

    detail = client.get(f"/api/detections/{listed[0]['id']}/")

    assert detail.status_code == 200
    assert detail.json()["signature"] == "path traversal"
                                                                             
    assert detail.json()["raw"]["fsl_source"] == "suricata"
    assert detail.json()["raw"]["alert"]["signature"] == "path traversal"

def test_the_detail_says_which_session_it_belongs_to(client, session_id):
    ingest(client, session_id, [alert("a")])
    listed = client.get(f"/api/sessions/{session_id}/detections/").json()

    detail = client.get(f"/api/detections/{listed[0]['id']}/").json()

    assert detail["session"] == session_id

def test_an_unknown_detection_is_404(client):
    assert client.get("/api/detections/9999/").status_code == 404

def test_an_ingest_that_could_not_read_everything_says_so(client, monkeypatch):
    from ingest import elastic

    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    monkeypatch.setattr(elastic, "fetch", lambda *a, **k: ([], (5000, 25937)))

    body = client.post_json(f"/api/sessions/{session_id}/ingest/").json()

    assert body["truncated"] == {"read": 5000, "total": 25937}, (
        "the window held more documents than one fetch can read and the reply "
        "did not say so, so the score is computed on part of the evidence"
    )

def test_an_ingest_that_read_everything_stays_quiet(client, monkeypatch):
    from ingest import elastic

    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    monkeypatch.setattr(elastic, "fetch", lambda *a, **k: ([], None))

    assert "truncated" not in client.post_json(
        f"/api/sessions/{session_id}/ingest/"
    ).json()
