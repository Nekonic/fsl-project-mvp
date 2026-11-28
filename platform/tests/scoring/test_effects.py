from datetime import timedelta

import pytest

from scoring import baseline as baselines
from scoring import losses
from scoring.models import ObjectiveLoss
from telemetry import events as log
from telemetry.events import Viewer
from testing.fakes import FakeTarget
from tests import rounds
from tests.scoring.targets import FIXTURES, ROGUE_ADMIN_AT, corp_state_runner

pytestmark = pytest.mark.django_db


def started(corp_target):
    found = rounds.opened(rounds.problem("corp"), started=ROGUE_ADMIN_AT - timedelta(minutes=5))
    baselines.take_baseline(found, corp_target)
    return found


def test_a_rogue_admin_the_target_recorded_during_an_attack_action_loses_the_objective(corp_target):
    found = started(corp_target)
    attack = rounds.action("act-3", ROGUE_ADMIN_AT - timedelta(seconds=2), seconds=4)

    fell = losses.observe_effects(found, corp_target, [attack])

    assert [fallen.key for fallen in fell] == ["corp-rogue-admin"]
    stored = ObjectiveLoss.objects.get(round=found)
    assert stored.attributed_marker == "act-3" and stored.achieved_at == ROGUE_ADMIN_AT
    assert [event["body"]["key"] for event in log.after(found.pk, 0, Viewer(staff=True)).events
            if event["kind"] == "objective.lost"] == ["corp-rogue-admin"]


def test_a_change_inside_two_attack_actions_spans_both_and_names_the_latest(corp_target):
    found = started(corp_target)
    long_run = rounds.action("act-1", ROGUE_ADMIN_AT - timedelta(seconds=30), seconds=40)
    attack = rounds.action("act-3", ROGUE_ADMIN_AT - timedelta(seconds=2), seconds=4)

    losses.observe_effects(found, corp_target, [attack, long_run])

    stored = ObjectiveLoss.objects.get(round=found)
    assert stored.attributed_marker == "act-3"
    assert stored.earliest < long_run.started_at and stored.latest > long_run.ended_at


def test_observing_again_loses_nothing_new(corp_target):
    found = started(corp_target)
    attack = rounds.action("act-3", ROGUE_ADMIN_AT - timedelta(seconds=2), seconds=4)
    losses.observe_effects(found, corp_target, [attack])

    assert losses.observe_effects(found, corp_target, [attack]) == ()
    assert ObjectiveLoss.objects.filter(round=found).count() == 1


def test_a_change_no_attack_action_overlaps_loses_the_objective_unattributed(corp_target):
    found = started(corp_target)
    benign = rounds.case("customer", ROGUE_ADMIN_AT - timedelta(seconds=1), malicious=False, seconds=3)
    earlier = rounds.action("act-1", ROGUE_ADMIN_AT - timedelta(minutes=3))

    fell = losses.observe_effects(found, corp_target, [benign, earlier])

    assert [fallen.key for fallen in fell] == ["corp-rogue-admin"]
    stored = ObjectiveLoss.objects.get(round=found)
    assert stored.attributed_marker is None and stored.achieved_at == ROGUE_ADMIN_AT


def test_a_change_the_target_recorded_after_the_round_s_end_time_loses_nothing():
    both = "".join((FIXTURES / name).read_text() for name in ("corp-rogue-admin.binlog", "corp-content-write.binlog"))
    target = FakeTarget({"corp-db": corp_state_runner(both)})
    found = started(target)
    later = ROGUE_ADMIN_AT + timedelta(hours=2)
    found.ends_at = ROGUE_ADMIN_AT + timedelta(minutes=1)
    found.save(update_fields=["ends_at"])
    attacks = [rounds.action("act-3", ROGUE_ADMIN_AT - timedelta(seconds=2), seconds=4),
               rounds.action("act-9", later - timedelta(hours=1), seconds=7200)]

    fell = losses.observe_effects(found, target, attacks)

    assert [fallen.key for fallen in fell] == ["corp-rogue-admin"]
    assert list(ObjectiveLoss.objects.filter(round=found).values_list("key", flat=True)) == ["corp-rogue-admin"]


def test_each_observation_records_when_the_target_was_read(corp_target):
    found = started(corp_target)

    losses.observe_effects(found, corp_target, [], now=ROGUE_ADMIN_AT)

    found.refresh_from_db()
    assert found.read_of["effects_read_at"] == ROGUE_ADMIN_AT.isoformat()
    assert found.read_of["changes"] > 0


def test_a_board_round_has_no_effects_to_observe(corp_target):
    found = rounds.opened(rounds.problem())

    assert losses.observe_effects(found, corp_target, []) == ()
    assert corp_target.reached == []
