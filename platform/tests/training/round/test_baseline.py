import pytest
from rest_framework.test import APIClient

from sandbox import service as sandbox
from tests.shape import refused
from training.models import BotBaseline, Round, RoundRecord
from training.round import baseline as baselines
from training.round import lifecycle
from training.round import records

KEY = "launcher-placeholder-key"


@pytest.fixture
def runner(settings, staff, cloud, forget_counts):
    settings.BOT_ROUND_USERS = frozenset({staff.username})
    settings.BOT_LAUNCHER_KEY = KEY
    settings.JUDGE_AFTER_SECONDS = 0
    return APIClient(REMOTE_ADDR="203.0.113.8", HTTP_AUTHORIZATION=f"Bearer {KEY}")


def baseline_url(problem) -> str:
    return f"/api/problems/{problem.pk}/baselines/"


def claimed_all(launcher) -> list[int]:
    runs = []
    while (answer := launcher.post("/api/bot-runs/claim/", {}, format="json")).status_code == 200:
        runs.append(answer.json()["run"])
    return runs


def finish_all(launcher, runs, exit_reason="success"):
    for run in runs:
        launcher.post(f"/api/bot-runs/{run}/finish/", {"exit": exit_reason}, format="json")


def refilled_and_advanced():
    baselines.advance()
    for _ in range(2):
        sandbox.advance_refills()
    baselines.advance()


def test_the_baseline_button_creates_one_20_round_baseline_per_allowed_side_and_step(as_staff, bot_problem, runner):
    made = [as_staff.post(baseline_url(bot_problem), {"human_side": "defence", "step": step}, format="json")
            for step in ("1", "2")]

    assert [answer.status_code for answer in made] == [201, 201]
    assert [(one.json()["step"], one.json()["wanted"], one.json()["attempts_max"]) for one in made] == [
        ("1", 20, 30), ("2", 20, 30)]
    refused(as_staff.post(baseline_url(bot_problem), {"human_side": "defence", "step": "1"}, format="json"),
            409, "baseline_running")
    refused(as_staff.post(baseline_url(bot_problem), {"human_side": "defence", "step": "3"}, format="json"),
            400, "step_not_allowed")
    refused(as_staff.post(baseline_url(bot_problem), {"human_side": "attack", "step": "1"}, format="json"),
            400, "step_not_allowed")


def test_a_bot_vs_bot_round_whose_runs_are_over_ends_with_bots_exited_and_is_judged_and_recorded(
        bot_problem, runner, staff):
    held = baselines.create(bot_problem.pk, "defence", "1", 1, staff)
    baselines.advance()
    found = Round.objects.get(baseline_of=held)
    assert found.matchup == "bot_vs_bot" and found.phase == "running"
    assert sorted(found.players.values_list("side", "step")) == [("attack", "1"), ("defence", "2")]

    finish_all(runner, claimed_all(runner))

    found.refresh_from_db()
    held.refresh_from_db()
    assert found.end_reason == "bots_exited" and found.judged_at is not None
    assert RoundRecord.objects.get(round_number=found.pk).counts_for_baseline
    assert (held.status, len(held.samples), held.exits) == ("current", 1, {"success": 2})
    assert found.allocation.closed is not None


def test_failed_runs_and_incomplete_records_do_not_count_and_the_baseline_fails_after_its_attempts(
        bot_problem, runner, staff):
    held = baselines.create(bot_problem.pk, "defence", "1", 1, staff)
    BotBaseline.objects.filter(pk=held.pk).update(attempts_max=2)
    baselines.advance()
    claimed_all(runner)
    runner.post("/api/bot-runs/claim/", {"restarted": True}, format="json")
    first = Round.objects.get(baseline_of=held)
    refilled_and_advanced()

    second = Round.objects.filter(baseline_of=held).exclude(pk=first.pk).get()
    assert not RoundRecord.objects.get(round_number=first.pk).counts_for_baseline
    finish_all(runner, claimed_all(runner), exit_reason="crashed")
    refilled_and_advanced()

    held.refresh_from_db()
    assert not RoundRecord.objects.get(round_number=second.pk).counts_for_baseline
    assert (held.status, held.attempts, held.samples) == ("failed", 2, [])


def test_a_baseline_round_staff_ended_gives_its_slot_back_once_judged_while_its_runs_still_run(
        bot_problem, runner, staff):
    held = baselines.create(bot_problem.pk, "defence", "1", 2, staff)
    baselines.advance()
    runs = claimed_all(runner)
    found = Round.objects.get(baseline_of=held)
    lifecycle.end_round(found, "ended_by_operator")
    baselines.advance()

    found.refresh_from_db()
    assert found.allocation.closed is not None and not RoundRecord.objects.filter(round_number=found.pk).exists()
    assert list(Round.objects.filter(baseline_of=held).values_list("pk", flat=True)) == [found.pk]
    finish_all(runner, runs)
    refilled_and_advanced()
    assert RoundRecord.objects.filter(round_number=found.pk).exists()
    assert Round.objects.filter(baseline_of=held).exclude(pk=found.pk).count() == 1


def test_the_percentile_shows_only_for_a_matching_current_baseline_and_publishing_needs_one(as_staff, bot_problem):
    document = as_staff.get(f"/api/staff/problems/{bot_problem.pk}/").json()
    document["problem"]["published"] = True
    published = {key: document[key] for key in ("problem", "round", "start_posture")}
    published["problem"] = {key: value for key, value in published["problem"].items()
                            if key not in ("id", "revision", "author", "updated")}

    refused(as_staff.put(f"/api/staff/problems/{bot_problem.pk}/", {**published, "base_revision": 1},
                         format="json"), 409, "baseline_missing")
    for step in ("1", "2"):
        BotBaseline.objects.create(problem=bot_problem, problem_revision=1, human_side="defence", step=step,
                                   profile_key=f"key-{step}", attempts_max=30, samples=[1.0], status="current")
    assert as_staff.put(f"/api/staff/problems/{bot_problem.pk}/", {**published, "base_revision": 1},
                        format="json").status_code == 200
    score = {"objectives": {"weighted": 1.0}}
    matching = RoundRecord.objects.create(round_number=1, matchup="def_vs_bot", profile_key="key-1", score=score)
    other = RoundRecord.objects.create(round_number=2, matchup="def_vs_bot", profile_key="key-9", score=score)
    assert records.standing_of(matching)["top_percent"] == 50.0
    assert records.standing_of(other) is None
