import pytest
from rest_framework.test import APIClient

from events import log
from tests.shape import refused


def test_staff_follow_a_round_s_events_by_cursor(as_staff):
    log.append(3, "round.started", {"ends_at": None})
    log.append(3, "seat.joined", {"side": "attack", "client": "bot"})

    page = as_staff.get("/api/rounds/3/events/").json()
    after = as_staff.get(f"/api/rounds/3/events/?after={page['next']}").json()

    assert [event["kind"] for event in page["events"]] == ["round.started", "seat.joined"]
    assert set(page["events"][0]) == {"id", "kind", "at", "seat_side", "body"}
    assert after == {"events": [], "next": page["next"]}


@pytest.mark.parametrize("cursor, code", [("-1", "min_value"), ("soon", "invalid")])
def test_a_bad_cursor_is_refused_by_path(as_staff, cursor, code):
    refused(as_staff.get(f"/api/rounds/3/events/?after={cursor}"), 400, code, path="after")


def test_a_learner_without_a_seat_is_refused_the_feed(as_learner):
    refused(as_learner.get("/api/rounds/3/events/"), 403, "not_staff")


@pytest.mark.django_db
def test_a_stranger_must_sign_in():
    refused(APIClient().get("/api/rounds/3/events/"), 401, "not_signed_in")
