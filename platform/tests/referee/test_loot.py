from datetime import datetime, timedelta, timezone

import pytest

from cr import errors
from events import log
from events.kinds import Viewer
from referee import service
from referee.models import Objective
from tests import rounds
from tests.referee.targets import TRUTH

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def started(board_target, objectives=()):
    found = rounds.opened(rounds.problem(objectives=objectives), started=AT - timedelta(minutes=30))
    service.take_baseline(found, board_target)
    return found


def lost_events(found, viewer):
    return [event["body"] for event in log.after(found.pk, 0, viewer).events if event["kind"] == "objective.lost"]


def test_the_admin_s_exact_stored_hash_loses_the_partial_and_admin_objectives(board_target):
    found = started(board_target)

    verdict = service.submit_loot(found, [{"username": "admin", "hash": TRUTH["admin"]}], at=AT)

    assert verdict.lost
    assert [fallen.key for fallen in verdict.fell] == ["board-auth-user-partial", "board-auth-user-admin"]
    assert verdict.objective.key == "board-auth-user-admin"
    assert sorted(Objective.objects.filter(round=found).values_list("key", flat=True)) == [
        "board-auth-user-admin", "board-auth-user-partial"]


def test_a_cracked_password_or_a_wrong_hash_loses_nothing(board_target):
    found = started(board_target)

    verdict = service.submit_loot(found, [{"username": "admin", "password": "admin1234"},
                                          {"username": "jiwoo", "hash": TRUTH["jiwoo"][:-2] + "x="}], at=AT)

    assert not verdict.lost and verdict.objective is None
    assert not Objective.objects.filter(round=found).exists()
    assert lost_events(found, Viewer(staff=True)) == []


def test_the_same_loot_twice_loses_each_objective_once(board_target):
    found = started(board_target)
    taken = {name: digest for name, digest in TRUTH.items()}

    first = service.submit_loot(found, taken, at=AT)
    second = service.submit_loot(found, taken, at=AT + timedelta(minutes=1))

    assert len(first.fell) == 3 and second.fell == ()
    assert Objective.objects.filter(round=found).count() == 3
    assert len(lost_events(found, Viewer(staff=True))) == 3


def test_only_the_objectives_the_round_put_at_stake_can_fall(board_target):
    found = started(board_target, objectives=["board-auth-user-admin"])

    verdict = service.submit_loot(found, [["jiwoo", TRUTH["jiwoo"]]], at=AT)

    assert not verdict.lost


def test_a_loss_is_announced_to_both_sides_and_its_attribution_only_to_staff(board_target):
    found = started(board_target)
    attack = rounds.action("act-7", AT - timedelta(seconds=30))

    service.submit_loot(found, {"admin": TRUTH["admin"]}, actions=[attack], at=AT)

    assert lost_events(found, Viewer(sides=frozenset({"defence"})))[-1] == {"key": "board-auth-user-admin",
                                                                           "name": "Board admin account"}
    assert lost_events(found, Viewer(staff=True))[-1]["attributed_marker"] == "act-7"


def test_the_loss_is_attributed_to_the_latest_attack_action_inside_the_window_and_never_to_a_benign_case(
        board_target):
    found = started(board_target)
    actions = [rounds.action("too-early", AT - timedelta(minutes=10)),
               rounds.action("earlier", AT - timedelta(seconds=90)),
               rounds.case("customer", AT - timedelta(seconds=5), malicious=False)]

    service.submit_loot(found, {"admin": TRUTH["admin"]}, actions=actions, at=AT)

    stored = Objective.objects.get(round=found, key="board-auth-user-admin")
    assert stored.attributed_marker == "earlier"
    assert stored.earliest == AT - timedelta(minutes=2) and stored.achieved_at == AT


def test_loot_with_no_attack_action_in_the_window_still_loses_the_objective_unattributed(board_target):
    found = started(board_target)

    service.submit_loot(found, {"admin": TRUTH["admin"]}, at=AT)

    assert Objective.objects.get(round=found, key="board-auth-user-admin").attributed_marker is None


def test_every_objective_the_round_put_at_stake_starts_kept_and_shows_lost_once_it_falls(board_target):
    found = started(board_target, objectives=["board-auth-user-partial", "board-auth-user-admin"])
    before = service.objectives(found)

    service.submit_loot(found, {"jiwoo": TRUTH["jiwoo"]}, at=AT)

    assert [(one.key, one.state) for one in before] == [("board-auth-user-partial", "kept"),
                                                        ("board-auth-user-admin", "kept")]
    assert [(one.key, one.state, one.seen) for one in service.objectives(found)] == [
        ("board-auth-user-partial", "lost", False), ("board-auth-user-admin", "kept", False)]


def test_a_wargame_judged_by_its_effects_takes_no_loot():
    found = rounds.opened(rounds.problem("corp"))

    with pytest.raises(errors.Conflict) as refused:
        service.submit_loot(found, {"admin": "anything"})

    assert refused.value.code == "loot_not_taken"


def test_loot_before_the_baseline_is_taken_is_refused():
    with pytest.raises(errors.Conflict) as refused:
        service.submit_loot(rounds.opened(rounds.problem()), {"admin": TRUTH["admin"]})

    assert refused.value.code == "round_not_started"
