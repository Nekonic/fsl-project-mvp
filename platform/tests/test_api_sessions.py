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

@pytest.mark.parametrize("write, payload", [
    ("cases/", CASE), ("attacks/", {"case": "sqli-login-bypass"}), ("objectives/", None),
])
def test_a_closed_session_takes_no_more_writes(client, closed, write, payload):
    response = client.post_json(f"/api/sessions/{closed}/{write}", payload)

    assert response.status_code == 409, (
        "a write after close lands outside the window the alert ingest covers, so a case "
        "can only ever be a miss and an attack reaches a stack being torn down"
    )

def test_a_closed_session_can_still_be_read(client, closed):
    assert client.get(f"/api/sessions/{closed}/").status_code == 200
    assert client.get(f"/api/sessions/{closed}/score/").status_code == 200
    assert client.get(f"/api/sessions/{closed}/objectives/").status_code == 200


def test_a_running_session_is_never_hidden_by_finished_ones(client):
    from django.utils import timezone

    from api.models import Session

    running = client.post_json("/api/sessions/", {}).json()["id"]
    for _ in range(SESSION_PAGE + 10):
        Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    listed = [s["id"] for s in client.get("/api/sessions/?state=open").json()]

    assert running in listed, (
        f"session {running} is still open and fell off the list behind "
        f"{SESSION_PAGE + 10} finished ones, so there is no way back to it"
    )

def test_asking_for_open_or_finished_sessions_lists_only_those(client):
    closed_id = client.post_json("/api/sessions/", {}).json()["id"]
    client.post_json(f"/api/sessions/{closed_id}/close/")
    open_id = client.post_json("/api/sessions/", {}).json()["id"]

    assert [s["id"] for s in client.get("/api/sessions/?state=open").json()] == [open_id]
    assert [s["id"] for s in client.get("/api/sessions/?state=closed").json()] == [closed_id]


def test_the_newest_sessions_are_the_ones_returned_up_to_the_limit_asked(client):
    made = []
    for _ in range(SESSION_PAGE + 3):
        made.append(client.post_json("/api/sessions/", {}).json()["id"])
        client.post_json(f"/api/sessions/{made[-1]}/close/")

    listed = [s["id"] for s in client.get("/api/sessions/").json()]

    assert listed == sorted(made, reverse=True)[:SESSION_PAGE]
    assert [s["id"] for s in client.get("/api/sessions/?limit=2").json()] == listed[:2]

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
