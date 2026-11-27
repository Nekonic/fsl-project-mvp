from datetime import timedelta

import pytest
from django.db.models.signals import post_delete
from django.utils import timezone
from rest_framework.test import APIClient

from tests.training.round.conftest import bot_round, pvp
from telemetry.models import Detection
from training.models import BotRun, Round, RoundRecord
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
    launcher.post(f"/api/bot-runs/{run}/finish/", {"exit": "success", "cost_usd": 0.4, "turns": 12,
                                                   "closing": "aimed at the account dump"}, format="json")

    assert records.keep_when_due(Round.objects.get(pk=found.pk)) is None
    service.end_round(found, "ended_by_operator")
    found.refresh_from_db()
    service.judge_late(found)
    records.keep_when_due(Round.objects.get(pk=found.pk))
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


def test_ending_the_round_ends_its_running_bot_and_the_bot_s_late_report_still_fills_in_its_cost(
        as_learner, allocation, bot_problem, opens_bot_rounds, launcher, settings):
    settings.JUDGE_AFTER_SECONDS = 0
    found = service.start_round(Round.objects.get(pk=bot_round(as_learner, allocation, bot_problem, opens_bot_rounds,
                                                               {"step": "1"}).json()["round"]))
    run = launcher.post("/api/bot-runs/claim/", {}, format="json").json()["run"]

    service.end_round(found, "ended_by_operator")
    found.refresh_from_db()
    ended = BotRun.objects.get(pk=run)
    assert (ended.status, ended.exit, ended.finished) == ("failed", "round_ended", found.ended)
    service.judge_late(found)
    assert records.keep_when_due(Round.objects.get(pk=found.pk)) is not None

    launcher.post(f"/api/bot-runs/{run}/finish/", {"exit": "timed_out", "cost_usd": 0.4, "turns": 12,
                                                   "closing": "aimed at the account dump"}, format="json")
    reported = BotRun.objects.get(pk=run)
    kept = RoundRecord.objects.get(round_number=found.pk)
    assert (reported.exit, reported.cost_usd, reported.turns, reported.finished) == ("round_ended", 0.4, 12,
                                                                                    found.ended)
    assert (kept.bot["attack"]["exit"], kept.bot["attack"]["cost_usd"]) == ("round_ended", 0.4)
    assert kept.debrief["bots"][0]["closing"] == "aimed at the account dump"


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


def test_the_score_of_a_kept_round_is_read_from_its_record_without_scoring_the_alerts_again(
        as_learner, allocation, learner, other, monkeypatch):
    found = service.start_round(pvp(allocation, other, learner))
    service.end_round(found, "ended_by_operator")
    kept = records.keep(Round.objects.get(pk=found.pk))
    monkeypatch.setattr(service, "score", lambda *given, **named: pytest.fail("scored again"))

    shown = as_learner.get(f"/api/rounds/{found.pk}/score/").json()

    assert shown["outcomes"]["totals"] == kept.score["outcomes"]["totals"]


def test_the_record_list_leaves_the_kept_score_and_debrief_unread(allocation, learner, other):
    found = service.start_round(pvp(allocation, other, learner))
    service.end_round(found, "ended_by_operator")
    records.keep(Round.objects.get(pk=found.pk))

    [line] = records.mine(learner)

    assert {"score", "debrief", "bot"} <= line.get_deferred_fields()


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
