"""Objectives: what the red team actually took, judged by the target itself.

The platform labels nothing here. Juice Shop decides whether it was beaten,
which is the point - a score the range produces about its own attacks is a
score the range can be wrong about.
"""

from unittest.mock import patch

import pytest

from objectives import ObjectivesUnavailable

pytestmark = pytest.mark.django_db

CATALOGUE = [
    {"key": "loginAdminChallenge", "name": "Login Admin", "category": "Injection",
     "difficulty": 2, "description": "", "solved": False},
    {"key": "basketAccessChallenge", "name": "View Basket",
     "category": "Broken Access Control", "difficulty": 2, "description": "", "solved": False},
    {"key": "errorHandlingChallenge", "name": "Error Handling",
     "category": "Security Misconfiguration", "difficulty": 1, "description": "", "solved": True},
]


def solved(*keys):
    return [dict(c, solved=c["key"] in keys) for c in CATALOGUE]


@pytest.fixture
def session_id(client):
    """A session opened while one objective was already solved by someone else."""
    with patch("api.views.objectives.solved_keys", return_value={"errorHandlingChallenge"}):
        return client.post_json("/api/sessions/", {}).json()["id"]


def poll(client, session_id, catalogue):
    with patch("api.views.objectives.catalogue", return_value=catalogue):
        return client.post_json(f"/api/sessions/{session_id}/objectives/")


def test_the_catalogue_lists_what_can_be_taken(client):
    with patch("api.views.objectives.catalogue", return_value=CATALOGUE):
        response = client.get("/api/wargames/juice-shop/objectives/")

    assert response.status_code == 200
    assert {o["name"] for o in response.json()} == {
        "Login Admin", "View Basket", "Error Handling"
    }


def test_objectives_solved_before_the_session_are_not_the_red_teams(client, session_id):
    # errorHandlingChallenge was already solved when the session opened.
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
        "api.views.objectives.catalogue",
        side_effect=ObjectivesUnavailable("juice-shop is down"),
    ):
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.status_code == 503
    assert "juice-shop is down" in response.json()["detail"]


def test_a_session_opened_blind_credits_nobody_for_what_came_before(client):
    # The target was unreachable at session creation, so the baseline is
    # unknown. Treating that as "nothing was solved" would hand the red team
    # every objective anyone had ever reached.
    with patch(
        "api.views.objectives.solved_keys",
        side_effect=ObjectivesUnavailable("down"),
    ):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]

    first = poll(client, session_id, solved("errorHandlingChallenge"))

    assert first.json()["achieved"] == 0
    assert first.json()["baseline"] == 1
    assert client.get(f"/api/sessions/{session_id}/objectives/").json() == []

    # And from here on it scores normally.
    later = poll(client, session_id, solved("errorHandlingChallenge", "loginAdminChallenge"))
    assert later.json()["achieved"] == 1
