import pytest
from rest_framework.test import APIClient

from events import log
from tests import rounds
from tests.shape import refused


@pytest.fixture
def found(db):
    return rounds.opened(rounds.problem())


def test_staff_follow_a_round_s_events_by_cursor(as_staff, found):
    log.append(found.pk, "round.started", {"ends_at": None})
    log.append(found.pk, "seat.joined", {"side": "attack", "client": "bot"})

    page = as_staff.get(f"/api/rounds/{found.pk}/events/").json()
    after = as_staff.get(f"/api/rounds/{found.pk}/events/?after={page['next']}").json()

    assert [event["kind"] for event in page["events"]] == ["round.started", "seat.joined"]
    assert set(page["events"][0]) == {"id", "kind", "at", "seat_side", "body"}
    assert after == {"events": [], "next": page["next"]}


@pytest.mark.parametrize("cursor, code", [("-1", "min_value"), ("soon", "invalid")])
def test_a_bad_cursor_is_refused_by_path(as_staff, found, cursor, code):
    refused(as_staff.get(f"/api/rounds/{found.pk}/events/?after={cursor}"), 400, code, path="after")


def test_a_learner_without_a_seat_is_refused_the_feed(as_learner, found):
    refused(as_learner.get(f"/api/rounds/{found.pk}/events/"), 403, "not_seated")


def test_each_seat_reads_only_its_side_s_kinds(browser, found, make_user):
    attacker, defender = make_user("red"), make_user("blue")
    rounds.seated(found, "attack", attacker)
    rounds.seated(found, "defence", defender)
    log.append(found.pk, "origin.spent", {"ip": "5.188.10.10"}, seat_side="attack")
    log.append(found.pk, "rule.applied", {"engine": "ids", "version": 1}, seat_side="defence")
    log.append(found.pk, "round.ended", {"reason": "time_limit"})

    browser.force_authenticate(attacker)
    seen_by_attack = [event["kind"] for event in browser.get(f"/api/rounds/{found.pk}/events/").json()["events"]]
    browser.force_authenticate(defender)
    seen_by_defence = [event["kind"] for event in browser.get(f"/api/rounds/{found.pk}/events/").json()["events"]]

    assert seen_by_attack == ["origin.spent", "round.ended"]
    assert seen_by_defence == ["rule.applied", "round.ended"]


@pytest.mark.django_db
def test_a_stranger_must_sign_in(found):
    refused(APIClient().get(f"/api/rounds/{found.pk}/events/"), 401, "not_signed_in")
