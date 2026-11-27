from datetime import timedelta

import pytest
from django.db.models.signals import post_delete
from django.utils import timezone
from rest_framework.test import APIClient

from tests.training.round.conftest import bot_round, pvp
from telemetry.models import Detection
from training.models import Round, RoundRecord
from training.round import allocation as allocations
from training.round import lifecycle as service
from training.round import records, retention

KEY = "launcher-placeholder-key"


@pytest.fixture
def launcher(settings, forget_counts):
    settings.BOT_LAUNCHER_KEY = KEY
    return APIClient(REMOTE_ADDR="203.0.113.8", HTTP_AUTHORIZATION=f"Bearer {KEY}")


def test_a_record_is_written_once_judged_and_the_runs_finished_and_survives_prune(
        as_learner, allocation, bot_problem, opens_bot_rounds, launcher, settings, make_user):
    settings.JUDGE_AFTER_SECONDS = 0
    found = service.start_round(Round.objects.get(pk=bot_round(as_learner, allocation, bot_problem, opens_bot_rounds,
                                                               {"step": "1"}).json()["round"]))
    run = launcher.post("/api/bot-runs/claim/", {}, format="json").json()["run"]
    service.end_round(found, "ended_by_operator")
    found.refresh_from_db()
    service.judge_late(found)

    assert records.keep_when_due(Round.objects.get(pk=found.pk)) is None
    launcher.post(f"/api/bot-runs/{run}/finish/", {"exit": "success", "cost_usd": 0.4, "turns": 12,
                                                   "closing": "aimed at the account dump"}, format="json")
    kept = RoundRecord.objects.get(round_number=found.pk)
    assert not kept.incomplete and kept.bot["attack"]["exit"] == "success" and kept.defence_user == opens_bot_rounds
    assert kept.debrief["bots"][0]["closing"] == "aimed at the account dump"

    allocations.close_allocation(allocation)
    settings.RETAIN_CLOSED_MINUTES = 0
    retention.prune(timezone.now() + timedelta(minutes=1))

    assert not Round.objects.filter(pk=found.pk).exists()
    assert as_learner.get(f"/api/records/{kept.pk}/").status_code == 200
    as_learner.force_authenticate(make_user("stranger"))
    assert as_learner.get(f"/api/records/{kept.pk}/").status_code == 403


def test_records_older_than_90_days_are_pruned(learner):
    score = {"objectives": {"weighted": 1.0}}
    RoundRecord.objects.create(round_number=1, matchup="def_vs_bot", score=score, defence_user=learner)
    RoundRecord.objects.create(round_number=2, matchup="def_vs_bot", score=score, defence_user=learner)
    RoundRecord.objects.filter(round_number=1).update(kept=timezone.now() - timedelta(days=91))

    assert records.prune() == 1

    assert list(RoundRecord.objects.values_list("round_number", flat=True)) == [2]


def test_a_pvp_record_names_its_wargame_and_no_problem(as_learner, allocation, learner, other):
    found = service.start_round(pvp(allocation, other, learner))
    service.end_round(found, "ended_by_operator")
    kept = records.keep(Round.objects.get(pk=found.pk))

    [line] = as_learner.get("/api/records/").json()
    assert kept.problem is None and (line["wargame"], line["problem"], line["problem_title"]) == ("board", None, None)


def test_a_detection_stored_while_its_round_is_deleted_goes_with_it(allocation, learner, other):
    found = service.start_round(pvp(allocation, other, learner))
    service.end_round(found, "ended_by_operator")
    allocations.close_allocation(allocation)

    def stored_late(sender, instance, **kwargs):
        Detection.objects.create(round_id=instance.pk, detection_id="late", engine="waf", timestamp=timezone.now())

    post_delete.connect(stored_late, sender=Round)
    try:
        retention.drop([allocation.pk])
    finally:
        post_delete.disconnect(stored_late, sender=Round)

    assert not Round.objects.filter(pk=found.pk).exists()
    assert not Detection.objects.filter(round_id=found.pk).exists()


def test_the_records_list_holds_only_the_users_own_rounds_of_published_problems(as_learner, learner, staff, problem):
    RoundRecord.objects.create(round_number=1, matchup="def_vs_bot", problem=problem, defence_user=learner)
    RoundRecord.objects.create(round_number=2, matchup="pvp", defence_user=learner)
    RoundRecord.objects.create(round_number=3, matchup="pvp", defence_user=staff)

    assert [line["round_number"] for line in as_learner.get("/api/records/").json()] == [2]
    as_learner.force_authenticate(staff)
    assert [line["round_number"] for line in as_learner.get("/api/records/").json()] == [3]
    problem.published = True
    problem.save()
    as_learner.force_authenticate(learner)
    assert [line["round_number"] for line in as_learner.get("/api/records/").json()] == [2, 1]
