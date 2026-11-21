from datetime import timedelta

import pytest

from scoring import baseline as baselines
from scoring import losses
from scoring.models import Objective
from telemetry import events as log
from telemetry.events import Viewer
from tests import rounds
from tests.scoring.targets import ROGUE_ADMIN_AT

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
    stored = Objective.objects.get(round=found)
    assert stored.attributed_marker == "act-3" and stored.achieved_at == ROGUE_ADMIN_AT
    assert [event["body"]["key"] for event in log.after(found.pk, 0, Viewer(staff=True)).events
            if event["kind"] == "objective.lost"] == ["corp-rogue-admin"]


def test_observing_again_loses_nothing_new(corp_target):
    found = started(corp_target)
    attack = rounds.action("act-3", ROGUE_ADMIN_AT - timedelta(seconds=2), seconds=4)
    losses.observe_effects(found, corp_target, [attack])

    assert losses.observe_effects(found, corp_target, [attack]) == ()
    assert Objective.objects.filter(round=found).count() == 1


def test_a_change_no_attack_action_overlaps_is_not_credited(corp_target):
    found = started(corp_target)
    benign = rounds.case("customer", ROGUE_ADMIN_AT - timedelta(seconds=1), malicious=False, seconds=3)
    earlier = rounds.action("act-1", ROGUE_ADMIN_AT - timedelta(minutes=3))

    assert losses.observe_effects(found, corp_target, [benign, earlier]) == ()
    assert not Objective.objects.filter(round=found).exists()


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
