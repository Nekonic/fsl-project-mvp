import pytest

from telemetry import events as kinds
from telemetry import events as log
from telemetry.events import Viewer
from telemetry.models import Event

ROUND = 7
ATTACKER = Viewer(sides=frozenset({"attack"}))
DEFENDER = Viewer(sides=frozenset({"defence"}))
OPERATOR = Viewer(operator=True)
STAFF = Viewer(staff=True)

SPEC_VISIBILITY = {
    "round.started": "both", "round.ended": "both", "player.joined": "both",
    "action.sent": "attack", "tool.started": "attack", "tool.ended": "attack", "command.run": "attack",
    "origin.spent": "attack", "origin.switched": "attack", "origins.spent": "attack",
    "alert.seen": "defence", "rule.tested": "defence", "rule.applied": "defence", "rule.disabled": "defence",
    "limit.below_floor": "defence", "case.judged": "defence", "objective.lost": "both",
}
AUDIENCES = {
    "both": kinds.BOTH, "attack": kinds.ATTACK_SIDE, "defence": kinds.DEFENCE_SIDE,
}


def a_round_of_play(round_id=ROUND):
    log.append(round_id, "round.started", {"ends_at": None})
    log.append(round_id, "action.sent", {"action": 1, "kind": "request", "status": 200}, player_side="attack")
    log.append(round_id, "alert.seen", {"alert": 4, "engine": "ids", "signature": "sqli"}, player_side="defence")
    log.append(round_id, "objective.lost", {"key": "secret", "name": "board secret", "attributed_marker": "case-1"})


def kinds_seen(viewer, round_id=ROUND):
    return [event["kind"] for event in log.after(round_id, 0, viewer).events]


def test_the_kind_table_is_the_one_the_design_names():
    assert {name: kind.visible_to for name, kind in kinds.KINDS.items()} == {
        name: AUDIENCES[audience] for name, audience in SPEC_VISIBILITY.items()}


@pytest.mark.django_db
def test_events_come_back_in_order_with_a_cursor_that_resumes():
    a_round_of_play()

    first = log.after(ROUND, 0, STAFF)
    log.append(ROUND, "round.ended", {"reason": "time_limit"})
    resumed = log.after(ROUND, first.next, STAFF)

    assert [event["kind"] for event in first.events] == ["round.started", "action.sent", "alert.seen",
                                                         "objective.lost"]
    assert [event["kind"] for event in resumed.events] == ["round.ended"]
    assert log.after(ROUND, resumed.next, STAFF).events == [] and log.after(ROUND, resumed.next, STAFF).next == \
        resumed.next


@pytest.mark.django_db
def test_in_pvp_each_side_sees_only_its_own_kinds():
    a_round_of_play()

    assert kinds_seen(ATTACKER) == ["round.started", "action.sent", "objective.lost"]
    assert kinds_seen(DEFENDER) == ["round.started", "alert.seen", "objective.lost"]
    assert kinds_seen(OPERATOR) == ["round.started", "objective.lost"]


@pytest.mark.django_db
def test_only_staff_see_who_an_objective_is_attributed_to():
    a_round_of_play()

    lost = {viewer: next(event for event in log.after(ROUND, 0, viewer).events if event["kind"] == "objective.lost")
            for viewer in (ATTACKER, STAFF)}

    assert lost[ATTACKER]["body"] == {"key": "secret", "name": "board secret"}
    assert lost[STAFF]["body"]["attributed_marker"] == "case-1"


@pytest.mark.django_db
def test_another_round_s_events_never_show():
    a_round_of_play(round_id=8)

    assert kinds_seen(STAFF) == []


@pytest.mark.django_db
def test_a_page_stops_at_the_limit_and_the_next_page_carries_on():
    for order in range(5):
        log.append(ROUND, "rule.applied", {"engine": "ids", "version": order, "source": "console"})

    first = log.after(ROUND, 0, STAFF, limit=3)
    rest = log.after(ROUND, first.next, STAFF, limit=3)

    assert [event["body"]["version"] for event in first.events + rest.events] == [0, 1, 2, 3, 4]


@pytest.mark.django_db
@pytest.mark.parametrize("kind, body, player_side, raised", [
    ("round.paused", {}, None, LookupError),
    ("round.ended", {}, None, TypeError),
    ("round.ended", {"reason": "x", "extra": 1}, None, TypeError),
    ("rule.applied", {"engine": "ids", "version": "first", "source": "console"}, None, TypeError),
    ("rule.applied", {"engine": "ids", "version": True, "source": "console"}, None, TypeError),
    ("round.ended", {"reason": "x"}, "referee", TypeError),
])
def test_a_malformed_event_is_refused_and_nothing_is_stored(kind, body, player_side, raised):
    with pytest.raises(raised):
        log.append(ROUND, kind, body, player_side=player_side)

    assert Event.objects.count() == 0


def test_the_event_has_no_relation_to_any_other_app():
    assert [field.name for field in Event._meta.get_fields() if field.is_relation] == []
