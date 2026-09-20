"""Objectives: what the red team actually took, judged by the target itself.

The platform labels nothing here. Juice Shop decides whether it was beaten,
which is the point - a score the range produces about its own attacks is a
score the range can be wrong about.
"""

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


CASE = {
    "case_id": "66666666-6666-4666-8666-666666666666",
    "name": "some-attack",
    "malicious": True,
    "correlation": "marker",
    "started_at": "2026-09-20T12:00:00Z",
    "ended_at": "2026-09-20T12:00:03Z",
}


def test_recording_a_case_notices_what_that_case_took(client, session_id):
    """The moment a case is reported is the moment to ask what fell.

    The red team reports every case as it finishes. Waiting for someone to
    poll at the end of a run stamps every objective with one time, and
    attribution then credits them all to whichever case happened to fire
    last - which in a run that ends on benign traffic is nobody.
    """
    with patch(
        "api.views.objectives.catalogue",
        return_value=solved("errorHandlingChallenge", "loginAdminChallenge"),
    ):
        created = client.post_json(f"/api/sessions/{session_id}/cases/", CASE)

    assert created.status_code == 201
    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()
    assert [o["name"] for o in taken] == ["Login Admin"]


def test_ground_truth_survives_a_target_that_cannot_be_asked(client, session_id):
    # The case is what the red team actually did. Losing it because the shop
    # would not answer a side question would put a real attack on record as
    # never having happened.
    with patch(
        "api.views.objectives.catalogue",
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
        "api.views.objectives.catalogue",
        return_value=solved("errorHandlingChallenge"),
    ):
        created = client.post_json(f"/api/sessions/{blind}/cases/", CASE)

    assert created.status_code == 201
    # The first poll establishes the baseline and credits nobody for it.
    assert client.get(f"/api/sessions/{blind}/objectives/").json() == []


def test_the_targets_own_solve_time_is_used_when_it_has_one(client, session_id):
    """Attribution is by time, so a stamp a poll late is a breach credited to
    the wrong attack - and the poll is always late, because the target flips
    `solved` after it has answered the request that did it.
    """
    # Anywhere between the session opening and now is believable. The session's
    # own start is the one instant this test can name exactly.
    solved_at = client.get(f"/api/sessions/{session_id}/").json()["started_at"]

    with patch(
        "api.views.objectives.catalogue",
        return_value=solved(
            "errorHandlingChallenge", "loginAdminChallenge", solved_at=solved_at,
        ),
    ):
        client.post_json(f"/api/sessions/{session_id}/objectives/")

    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()

    assert taken[0]["achieved_at"] == solved_at


def test_a_solve_time_older_than_the_session_is_not_believed(client, session_id):
    # The target rewrites every updatedAt in bulk when it restores its own
    # state, so a stamp from before this session opened is not a solve time.
    from django.utils import timezone

    before = timezone.now() - timedelta(days=2)
    with patch(
        "api.views.objectives.catalogue",
        return_value=solved(
            "errorHandlingChallenge", "loginAdminChallenge",
            solved_at=before.isoformat(),
        ),
    ):
        client.post_json(f"/api/sessions/{session_id}/objectives/")

    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()

    assert not taken[0]["achieved_at"].startswith(before.isoformat()[:10])
