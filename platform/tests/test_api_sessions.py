import pytest

pytestmark = pytest.mark.django_db

SESSION_PAGE = 25

CASE = {
    "case_id": "11111111-1111-1111-1111-111111111111",
    "name": "after-close", "malicious": True, "correlation": "window",
    "started_at": "2026-09-21T10:00:00Z", "ended_at": "2026-09-21T10:00:05Z",
}

@pytest.fixture
def closed(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{session_id}/close/")
    return session_id

def test_a_closed_session_takes_no_more_cases(client, closed):
    response = client.post_json(f"/api/sessions/{closed}/cases/", CASE)

    assert response.status_code == 409, (
        "a case recorded after the session closed is scored against a window "
        "the alert ingest no longer covers, so it can only ever be a miss"
    )

def test_a_closed_session_fires_no_more_attacks(client, closed):
    response = client.post_json(
        f"/api/sessions/{closed}/attacks/", {"case": "sqli-login-bypass"}
    )

    assert response.status_code == 409

def test_a_closed_session_claims_no_more_objectives(client, closed):
    response = client.post_json(f"/api/sessions/{closed}/objectives/")

    assert response.status_code == 409

def test_a_closed_session_can_still_be_read(client, closed):
    assert client.get(f"/api/sessions/{closed}/").status_code == 200
    assert client.get(f"/api/sessions/{closed}/score/").status_code == 200
    assert client.get(f"/api/sessions/{closed}/objectives/").status_code == 200


def test_a_running_session_is_never_hidden_by_finished_ones(client):
    running = client.post_json("/api/sessions/", {}).json()["id"]
    for _ in range(SESSION_PAGE + 10):
        later = client.post_json("/api/sessions/", {}).json()["id"]
        client.post_json(f"/api/sessions/{later}/close/")

    listed = [s["id"] for s in client.get("/api/sessions/?state=open").json()]

    assert running in listed, (
        f"session {running} is still open and fell off the list behind "
        f"{SESSION_PAGE + 10} finished ones, so there is no way back to it"
    )

def test_asking_for_open_sessions_excludes_the_finished_ones(client):
    open_id = client.post_json("/api/sessions/", {}).json()["id"]
    closed_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{closed_id}/close/")

    listed = [s["id"] for s in client.get("/api/sessions/?state=open").json()]

    assert open_id in listed
    assert closed_id not in listed

def test_asking_for_finished_sessions_excludes_the_running_ones(client):
    open_id = client.post_json("/api/sessions/", {}).json()["id"]
    closed_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{closed_id}/close/")

    listed = [s["id"] for s in client.get("/api/sessions/?state=closed").json()]

    assert closed_id in listed
    assert open_id not in listed


def test_the_session_list_is_bounded_so_a_long_lived_range_stays_usable(client):
    for _ in range(SESSION_PAGE + 5):
        client.post_json("/api/sessions/", {})

    listed = client.get("/api/sessions/").json()

    assert len(listed) == SESSION_PAGE, (
        f"the list returned {len(listed)} sessions; an unbounded list means every "
        f"landing page load ships the whole history"
    )

def test_the_newest_sessions_are_the_ones_returned(client):
    made = [client.post_json("/api/sessions/", {}).json()["id"]
            for _ in range(SESSION_PAGE + 3)]

    listed = [s["id"] for s in client.get("/api/sessions/").json()]

    assert listed == sorted(made, reverse=True)[:SESSION_PAGE]

def test_asking_for_fewer_sessions_returns_fewer(client):
    for _ in range(4):
        client.post_json("/api/sessions/", {})

    assert len(client.get("/api/sessions/?limit=2").json()) == 2

@pytest.mark.parametrize("scenario", ["nope", ["x"], 3])
def test_a_session_for_a_wargame_that_does_not_exist_is_refused(client, scenario):
    from api.models import Session

    response = client.post_json("/api/sessions/", {"scenario": scenario})

    assert response.status_code == 400, (
        f"a session was opened for {scenario!r}: every attack fired into it is "
        f"looked up in a catalogue that does not exist, and its score is judged "
        f"against no expectations at all"
    )
    assert not Session.objects.exists()

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
