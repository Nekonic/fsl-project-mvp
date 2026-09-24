from datetime import timedelta
from unittest.mock import patch

import pytest

from objectives import ObjectivesUnavailable

pytestmark = pytest.mark.django_db

CATALOGUE = [
    {"key": "loginAdminChallenge", "name": "Login Admin", "category": "Injection",
     "difficulty": 2, "description": "", "solved": False, "solved_at": None},
    {"key": "basketAccessChallenge", "name": "View Basket",
     "category": "Broken Access Control", "difficulty": 2, "description": "",
     "solved": False, "solved_at": None},
    {"key": "errorHandlingChallenge", "name": "Error Handling",
     "category": "Security Misconfiguration", "difficulty": 1, "description": "",
     "solved": True, "solved_at": None},
]

def solved(*keys, solved_at=None):
    return [
        dict(c, solved=c["key"] in keys, solved_at=solved_at if c["key"] in keys else None)
        for c in CATALOGUE
    ]

@pytest.fixture
def session_id(client):
    with patch("api.views.objectives.solved_keys", return_value={"errorHandlingChallenge"}):
        return client.post_json("/api/sessions/", {}).json()["id"]

def poll(client, session_id, catalogue):
    with patch("api.views.objectives.observe", return_value=(catalogue, "")):
        return client.post_json(f"/api/sessions/{session_id}/objectives/")

def test_the_catalogue_lists_what_can_be_taken(client):
    with patch("api.views.objectives.catalogue", return_value=CATALOGUE):
        response = client.get("/api/wargames/juice-shop/objectives/")

    assert response.status_code == 200
    assert {o["name"] for o in response.json()} == {
        "Login Admin", "View Basket", "Error Handling"
    }

def test_objectives_solved_before_the_session_are_not_the_red_teams(client, session_id):
    assert poll(client, session_id, solved("errorHandlingChallenge")).json()["achieved"] == 0
    assert client.get(f"/api/sessions/{session_id}/objectives/").json() == []

def test_an_objective_taken_during_the_session_is_recorded(client, session_id):
    response = poll(client, session_id, solved("errorHandlingChallenge", "loginAdminChallenge"))

    assert response.json()["achieved"] == 1
    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()
    assert [o["name"] for o in taken] == ["Login Admin"]
    assert taken[0]["difficulty"] == 2
    assert taken[0]["category"] == "Injection"

def test_polling_again_records_nothing_twice(client, session_id):
    both = solved("errorHandlingChallenge", "loginAdminChallenge")
    poll(client, session_id, both)

    assert poll(client, session_id, both).json()["achieved"] == 0
    assert len(client.get(f"/api/sessions/{session_id}/objectives/").json()) == 1

def test_a_target_that_cannot_be_reached_is_503_not_an_empty_scoreboard(client, session_id):
    with patch(
        "api.views.objectives.observe",
        side_effect=ObjectivesUnavailable("juice-shop is down"),
    ):
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.status_code == 503
    assert "juice-shop is down" in response.json()["detail"]

def test_a_session_opened_blind_credits_nobody_for_what_came_before(client):
    with patch(
        "api.views.objectives.solved_keys",
        side_effect=ObjectivesUnavailable("down"),
    ):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]

    first = poll(client, session_id, solved("errorHandlingChallenge"))

    assert first.json()["achieved"] == 0
    assert first.json()["baseline"] == 1
    assert client.get(f"/api/sessions/{session_id}/objectives/").json() == []

    later = poll(client, session_id, solved("errorHandlingChallenge", "loginAdminChallenge"))
    assert later.json()["achieved"] == 1

CASE = {
    "case_id": "66666666-6666-4666-8666-666666666666",
    "name": "some-attack",
    "malicious": True,
    "correlation": "marker",
    "started_at": "2026-09-20T12:00:00Z",
    "ended_at": "2026-09-20T12:00:03Z",
}

def test_recording_a_case_notices_what_that_case_took(client, session_id):
    with patch(
        "api.views.objectives.observe",
        return_value=(solved("errorHandlingChallenge", "loginAdminChallenge"), ""),
    ):
        created = client.post_json(f"/api/sessions/{session_id}/cases/", CASE)

    assert created.status_code == 201
    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()
    assert [o["name"] for o in taken] == ["Login Admin"]

def test_ground_truth_survives_a_target_that_cannot_be_asked(client, session_id):
    with patch(
        "api.views.objectives.observe",
        side_effect=ObjectivesUnavailable("juice-shop is down"),
    ):
        created = client.post_json(f"/api/sessions/{session_id}/cases/", CASE)

    assert created.status_code == 201
    assert client.get(f"/api/sessions/{session_id}/cases/").json()[0]["name"] == "some-attack"

def test_a_session_with_no_baseline_still_records_cases(client):
    with patch(
        "api.views.objectives.solved_keys", side_effect=ObjectivesUnavailable("down")
    ):
        blind = client.post_json("/api/sessions/", {}).json()["id"]

    with patch(
        "api.views.objectives.observe",
        return_value=(solved("errorHandlingChallenge"), ""),
    ):
        created = client.post_json(f"/api/sessions/{blind}/cases/", CASE)

    assert created.status_code == 201
    assert client.get(f"/api/sessions/{blind}/objectives/").json() == []

def test_the_targets_own_solve_time_is_used_when_it_has_one(client, session_id):
    solved_at = client.get(f"/api/sessions/{session_id}/").json()["started_at"]

    with patch(
        "api.views.objectives.observe",
        return_value=(solved(
            "errorHandlingChallenge", "loginAdminChallenge", solved_at=solved_at,
        ), ""),
    ):
        client.post_json(f"/api/sessions/{session_id}/objectives/")

    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()

    assert taken[0]["achieved_at"] == solved_at

def test_a_solve_time_older_than_the_session_is_not_believed(client, session_id):
    from django.utils import timezone

    before = timezone.now() - timedelta(days=2)
    with patch(
        "api.views.objectives.observe",
        return_value=(solved(
            "errorHandlingChallenge", "loginAdminChallenge",
            solved_at=before.isoformat(),
        ), ""),
    ):
        client.post_json(f"/api/sessions/{session_id}/objectives/")

    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()

    assert not taken[0]["achieved_at"].startswith(before.isoformat()[:10])

def test_a_session_opens_while_the_wiki_cannot_be_asked(client):
    with patch("objectives._fetch", return_value=[]):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 201, (
        "the wiki is a container the red team can take down, and opening a "
        "session asked it for the baseline and died with a bare 500"
    )
    from api.models import Session

    assert Session.objects.get(pk=response.json()["id"]).baseline is None, (
        "with no baseline the first poll takes one, rather than crediting the "
        "red team with everything already solved"
    )

def test_objectives_say_why_the_wiki_cannot_be_asked(client):
    with patch("objectives._fetch", return_value=[]):
        response = client.get("/api/wargames/juice-shop/objectives/")

    internal = next(o for o in response.json() if o["key"] == "internalRunbookRead")
    assert internal["solved"] is None
    assert "wiki" in internal["unreadable"]

def test_the_board_keeps_the_targets_objectives_when_only_the_wiki_cannot_be_asked(client):
    taken = {"key": "loginAdminChallenge", "name": "Login Admin", "category": "Injection",
             "difficulty": 2, "solved": True, "updatedAt": None}
    with patch("objectives._fetch", return_value=[taken]):
        response = client.get("/api/wargames/juice-shop/objectives/")

    assert response.status_code == 200, (
        "the wiki could not be read and the whole board answered 503, so the "
        "red console replaced every Juice Shop objective with an error at the "
        "moment one of them fell"
    )
    board = {o["key"]: o["solved"] for o in response.json()}
    assert board == {"loginAdminChallenge": True, "internalRunbookRead": None}
