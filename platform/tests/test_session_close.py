from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Session
from objectives import ObjectivesUnavailable

pytestmark = pytest.mark.django_db

JUICE = [{
    "key": "loginAdminChallenge", "name": "Login Admin", "category": "Injection",
    "difficulty": 2, "description": "", "solved": False,
}]


def solved(at=None):
    return [dict(JUICE[0], solved=True, updatedAt=at)]


@pytest.fixture
def session_id(client):
    with patch("objectives._fetch", return_value=JUICE), patch(
        "objectives._internal", return_value={"key": "internalRunbookRead", "name": "x",
                                              "category": "", "difficulty": 1,
                                              "description": "", "solved": False,
                                              "solved_at": None},
    ):
        return client.post_json("/api/sessions/", {}).json()["id"]


def test_a_closed_session_cannot_be_closed_again(client, session_id):
    with patch("objectives._fetch", return_value=JUICE):
        first = client.post_json(f"/api/sessions/{session_id}/close/")
    closed_at = Session.objects.get(pk=session_id).ended_at
    with patch("objectives._fetch", return_value=solved()), patch(
        "django.utils.timezone.now", return_value=timezone.now() + timedelta(days=1)
    ):
        again = client.post_json(f"/api/sessions/{session_id}/close/")

    assert first.status_code == 200
    assert again.status_code == 409, (
        f"closing a closed session answered {again.status_code} and moved its end "
        f"a day later, widening the window its alerts are read from into other "
        f"sessions' traffic"
    )
    assert Session.objects.get(pk=session_id).ended_at == closed_at
    assert client.get(f"/api/sessions/{session_id}/objectives/").json() == [], (
        "a breach from the day after was recorded into a session already closed"
    )


def test_what_the_target_lost_since_the_last_poll_is_recorded_at_close(client, session_id):
    with patch("objectives._fetch", return_value=solved()):
        client.post_json(f"/api/sessions/{session_id}/close/")

    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()

    assert [o["key"] for o in taken] == ["loginAdminChallenge"], (
        "the board polls every ten seconds and nothing polled at close, so a "
        "breach in the last few seconds was never recorded and the session "
        "read as untouched"
    )


def test_a_wiki_that_cannot_be_read_does_not_throw_away_what_the_target_said(client, session_id):
    with patch("objectives._fetch", return_value=solved()):
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.status_code == 200, (
        f"the wiki was unreadable and Juice Shop answered, and all of Juice "
        f"Shop's verdicts were discarded with a {response.status_code}"
    )
    assert response.json()["achieved"] == 1
    assert "wiki" in response.json()["unreadable"]


def test_an_attack_that_was_running_when_the_session_closed_is_still_in_its_window(client, session_id):
    a_case = client.get("/api/wargames/juice-shop/cases/").json()[0]["name"]

    def closes_meanwhile(*args, **kwargs):
        with patch("objectives._fetch", return_value=JUICE):
            client.post_json(f"/api/sessions/{session_id}/close/")

    with patch("api.views.harness.fire", side_effect=closes_meanwhile), patch(
        "api.views._observe_objectives", return_value={"achieved": 0}
    ), patch("api.views._origin_for", return_value=None):
        response = client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": a_case})

    assert response.status_code == 201, response.content
    session = Session.objects.get(pk=session_id)
    recorded = session.cases.get()
    assert session.ended_at >= recorded.ended_at, (
        "the attack reached the target and was recorded, but its session had "
        "closed while it ran, so its evidence fell outside the window it is "
        "scored from and it counted as a miss"
    )


def test_two_observations_at_once_record_an_objective_once(client, session_id):
    from api import views
    from api.models import Objective

    real = views._achieved
    underway = []

    def overtaken(objective, session, observed_at):
        if not underway:
            underway.append(True)
            with patch("objectives._fetch", return_value=solved()):
                client.post_json(f"/api/sessions/{session_id}/objectives/")
        return real(objective, session, observed_at)

    with patch("objectives._fetch", return_value=solved()), patch(
        "api.views._achieved", side_effect=overtaken
    ):
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.status_code == 200, (
        f"a console poll and a close observed the target at once, both saw "
        f"the objective as new, and the second died on the unique constraint: "
        f"{response.status_code}"
    )
    assert Objective.objects.filter(session_id=session_id).count() == 1


def fire_closing_meanwhile(client, session_id, target, breach_during_fire):
    a_case = client.get("/api/wargames/juice-shop/cases/").json()[0]["name"]

    def closes_then_breaches(*args, **kwargs):
        client.post_json(f"/api/sessions/{session_id}/close/")
        if breach_during_fire:
            target["challenges"] = solved(timezone.now().isoformat())

    with patch("objectives._fetch", side_effect=lambda: target["challenges"]), patch(
        "api.views.harness.fire", side_effect=closes_then_breaches
    ), patch("api.views._origin_for", return_value=None):
        return client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": a_case})


def test_what_an_attack_still_running_at_close_took_is_on_the_board(client, session_id):
    response = fire_closing_meanwhile(client, session_id, {"challenges": JUICE}, True)

    assert response.status_code == 201, response.content
    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()
    assert [o["key"] for o in taken] == ["loginAdminChallenge"], (
        "the close read the target before the attack still running took the "
        "objective, every later observation was refused as closed, and the "
        "breach inside the stretched window reached no board"
    )
    score = client.get(f"/api/sessions/{session_id}/score/").json()
    assert score["objectives"]["objectives"] == 1


def test_a_solve_the_target_records_a_moment_after_the_attack_is_still_seen(
    client, session_id, settings
):
    settings.TARGET_SETTLE = 0.25
    target = {"challenges": JUICE}

    def target_catches_up(seconds):
        if seconds == settings.TARGET_SETTLE:
            target["challenges"] = solved(timezone.now().isoformat())

    with patch("api.views.time.sleep", side_effect=target_catches_up):
        response = fire_closing_meanwhile(client, session_id, target, False)

    assert response.status_code == 201, response.content
    taken = client.get(f"/api/sessions/{session_id}/objectives/").json()
    assert [o["key"] for o in taken] == ["loginAdminChallenge"], (
        "the target records a solve a moment after answering the request that "
        "earned it, and the fire read the target before that moment"
    )


def test_a_target_that_cannot_be_read_after_the_attack_does_not_lose_the_attack(
    client, session_id
):
    a_case = client.get("/api/wargames/juice-shop/cases/").json()[0]["name"]

    with patch("objectives._fetch", side_effect=ObjectivesUnavailable("timed out")), patch(
        "api.views.harness.fire"
    ), patch("api.views._origin_for", return_value=None):
        response = client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": a_case})

    assert response.status_code == 201, response.content
    assert Session.objects.get(pk=session_id).cases.count() == 1
