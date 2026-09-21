import pytest

pytestmark = pytest.mark.django_db

def test_create_session_returns_id_and_start_time(client):
    response = client.post_json("/api/sessions/", {"scenario": "juice-shop"})

    assert response.status_code == 201
    assert response.json()["id"]
    assert response.json()["started_at"]
    assert response.json()["ended_at"] is None

def test_record_case_then_read_it_back(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    payload = {
        "case_id": "11111111-1111-4111-8111-111111111111",
        "name": "sqli-login-bypass",
        "malicious": True,
        "technique": "SQLi",
        "correlation": "marker",
        "source_ip": "172.20.0.5",
        "started_at": "2026-09-18T12:00:00Z",
        "ended_at": "2026-09-18T12:00:03Z",
        "meta": {"path": "/rest/user/login"},
    }

    created = client.post_json(f"/api/sessions/{session_id}/cases/", payload)
    assert created.status_code == 201

    listed = client.get(f"/api/sessions/{session_id}/cases/")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["name"] == "sqli-login-bypass"
    assert listed.json()[0]["malicious"] is True

def test_case_rejects_unknown_correlation_strategy(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    payload = {
        "case_id": "22222222-2222-4222-8222-222222222222",
        "name": "bad",
        "malicious": True,
        "correlation": "fuzzy",
        "started_at": "2026-09-18T12:00:00Z",
        "ended_at": "2026-09-18T12:00:03Z",
    }

    response = client.post_json(f"/api/sessions/{session_id}/cases/", payload)

    assert response.status_code == 400
    assert "correlation" in response.json()

def test_closing_session_sets_end_time(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    response = client.post_json(f"/api/sessions/{session_id}/close/")

    assert response.status_code == 200
    assert response.json()["ended_at"] is not None

def test_cases_for_missing_session_are_404(client):
    response = client.get("/api/sessions/9999/cases/")

    assert response.status_code == 404

def test_case_model_converts_to_scoring_record(client):
    from api.models import Case
    from scoring.types import CaseRecord

    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{session_id}/cases/", {
            "case_id": "33333333-3333-4333-8333-333333333333",
            "name": "n",
            "malicious": False,
            "correlation": "window",
            "source_ip": "10.0.0.1",
            "started_at": "2026-09-18T12:00:00Z",
            "ended_at": "2026-09-18T12:00:03Z",
        },
    )

    record = Case.objects.get().to_record()

    assert isinstance(record, CaseRecord)
    assert record.correlation == "window"
    assert record.source_ip == "10.0.0.1"
    assert record.malicious is False
