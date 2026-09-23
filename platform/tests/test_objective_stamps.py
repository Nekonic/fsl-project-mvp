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
