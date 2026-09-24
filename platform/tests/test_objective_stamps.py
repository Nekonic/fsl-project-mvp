from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.views import _achieved

SESSION = SimpleNamespace(started_at=datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc))
OBSERVED = datetime(2026, 9, 24, 10, 5, 0, tzinfo=timezone.utc)


def test_a_millisecond_stamp_is_believed_to_the_millisecond():
    at, earliest, latest = _achieved({"solved_at": "2026-09-24T10:01:02.194Z"}, SESSION, OBSERVED)

    assert at == datetime(2026, 9, 24, 10, 1, 2, 194000, tzinfo=timezone.utc)
    assert latest - earliest < timedelta(milliseconds=300)


def test_a_stamp_to_the_second_is_believed_only_to_the_second():
    at, earliest, latest = _achieved({"solved_at": "2026-09-24T10:01:02+00:00"}, SESSION, OBSERVED)

    assert latest >= at + timedelta(seconds=1), (
        "nginx writes the wiki's read log to the second, so a read at .900 is "
        "stamped .000 and fell before the case that caused it"
    )


def test_without_a_stamp_the_breach_is_somewhere_before_it_was_seen():
    at, earliest, latest = _achieved({"solved_at": None}, SESSION, OBSERVED)

    assert (at, earliest, latest) == (OBSERVED, None, None)


@pytest.mark.django_db
def test_the_interval_a_stamp_allows_is_kept_with_the_objective(client):
    from django.utils import timezone

    from api.models import Objective

    with patch("api.views.objectives.solved_keys", return_value=set()):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]
    stamp = timezone.now().isoformat(timespec="milliseconds")
    taken = [{"key": "loginAdminChallenge", "name": "Login Admin", "category": "Injection",
              "difficulty": 2, "solved": True, "solved_at": stamp}]

    with patch("api.views.objectives.observe", return_value=(taken, "")):
        client.post_json(f"/api/sessions/{session_id}/objectives/")

    recorded = Objective.objects.get(session_id=session_id)
    assert recorded.earliest and recorded.latest, (
        "the score attributes a breach from the interval stored with it; with "
        "none stored it fell back to two minutes after every case"
    )
    assert recorded.latest - recorded.earliest < timedelta(milliseconds=300)


CHECKED_ON_THE_NEXT_REQUEST = {"key": "feedbackChallenge", "name": "Five-Star Feedback",
                               "category": "Broken Access Control", "difficulty": 2}
CHECKED_DURING_THE_ATTACK = {"key": "loginAdminChallenge", "name": "Login Admin",
                             "category": "Injection", "difficulty": 2}
WINDOW = "44444444-4444-4444-8444-444444444444"


def _stamped_after_a_detected_window(client, challenge, after):
    from api.models import Session
    from tests.test_api_corroboration import T0, alert

    ended = T0 + timedelta(seconds=20)
    target = []
    with patch("objectives._fetch", side_effect=lambda: target):
        with patch("api.views.objectives.solved_keys", return_value=set()):
            session_id = client.post_json("/api/sessions/", {}).json()["id"]
        Session.objects.filter(pk=session_id).update(started_at=T0 - timedelta(minutes=1))
        client.post_json(f"/api/sessions/{session_id}/cases/", {
            "case_id": WINDOW, "name": "manual-window", "malicious": True,
            "correlation": "marker", "started_at": T0.isoformat(),
            "ended_at": ended.isoformat(),
        })
        with patch("api.views.elastic.fetch", return_value=([alert(WINDOW, "FSL anything")], None)):
            client.post_json(f"/api/sessions/{session_id}/ingest/")
        stamp = (ended + after).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        target.append(dict(challenge, solved=True, updatedAt=stamp))
        client.post_json(f"/api/sessions/{session_id}/objectives/")
    return client.get(f"/api/sessions/{session_id}/score/").json()


@pytest.mark.django_db
def test_a_challenge_the_target_checks_on_its_next_request_belongs_to_the_window_before_it(client):
    score = _stamped_after_a_detected_window(
        client, CHECKED_ON_THE_NEXT_REQUEST, timedelta(milliseconds=300)
    )

    assert [c["verdict"] for c in score["per_case"]] == ["TP"]
    assert [(b["key"], b["detected"]) for b in score["breaches"]] == [
        ("feedbackChallenge", True)
    ], (
        "Juice Shop solves feedbackChallenge in databaseRelatedChallenges on "
        "the request after the deed, usually our own poll, so its stamp is "
        "when it was checked. Read as the moment of the breach it fell after "
        "the window that took it and scored undetected at full damage"
    )
    assert score["objectives"]["detected"] == 1


@pytest.mark.django_db
def test_a_challenge_the_target_solves_during_the_attack_keeps_its_narrow_interval(client):
    score = _stamped_after_a_detected_window(
        client, CHECKED_DURING_THE_ATTACK, timedelta(milliseconds=300)
    )

    assert [(b["key"], b["detected"]) for b in score["breaches"]] == [
        ("loginAdminChallenge", False)
    ]


@pytest.mark.django_db
def test_a_breach_row_carries_the_objective_and_the_alerts_that_saw_it(client):
    score = _stamped_after_a_detected_window(
        client, CHECKED_ON_THE_NEXT_REQUEST, timedelta(milliseconds=300)
    )

    assert score["breaches"] == [
        dict(CHECKED_ON_THE_NEXT_REQUEST, detected=True, detection_ids=["es1"])
    ]
