from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from cr import errors
from domain import baseline as ranks
from domain.round_rules import BOTS_EXITED, Matchup, Phase
from training.content import bots as catalog
from training.content import problems as content
from training.models import BotBaseline, BotRun, Round, RoundRecord
from training.round import allocation as allocations
from training.round import bots as bot_runs
from training.round import lifecycle, records

RUNNING, CURRENT, STALE, FAILED = "running", "current", "stale", "failed"
EXTRA_ATTEMPTS = 10
RUNS_GIVEN_UP_AFTER = timedelta(minutes=20)
OPEN = (Phase.CREATED.value, Phase.STARTING.value, Phase.RUNNING.value)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Line:
    baseline: BotBaseline
    spread: ranks.Spread


def refuse_closed(by) -> None:
    if by is None or by.username not in settings.BOT_ROUND_USERS:
        raise errors.NotAPlayer(code="bot_rounds_closed")


def create(problem_id: int, human_side: str, step: str, rounds: int, by) -> BotBaseline:
    refuse_closed(by)
    problem = content.problem(problem_id)
    setup = content.snapshot(problem).get("round") or {}
    if (human_side, step) not in content.baselines_wanted(setup):
        raise errors.Invalid(code="step_not_allowed", path="step")
    if not setup.get("cards"):
        raise errors.Invalid(code="cards_missing", path="step")
    if BotBaseline.objects.filter(problem=problem, human_side=human_side, step=step, status=RUNNING).exists():
        raise errors.Conflict(code="baseline_running")
    return BotBaseline.objects.create(problem=problem, problem_revision=problem.revision, human_side=human_side,
                                      step=step, rounds_wanted=rounds, attempts_max=rounds + EXTRA_ATTEMPTS,
                                      created_by=by)


def seats(held: BotBaseline) -> dict[str, dict]:
    opponent = records.OTHER_SIDE[held.human_side]
    return {opponent: {"bot": {"step": held.step}},
            held.human_side: {"bot": {"step": catalog.stand_in(held.human_side)}}}


def open_next(held: BotBaseline) -> Round | None:
    try:
        taken = allocations.open_allocation(None, held.problem.wargame_id)
    except errors.Unavailable:
        return None
    BotBaseline.objects.filter(pk=held.pk).update(attempts=held.attempts + 1)
    held.attempts += 1
    try:
        made = lifecycle.create_round(taken, held.problem_id, Matchup.BOT_VS_BOT.value, seats(held),
                                      baseline=held).round
        return lifecycle.start_round(made)
    except Exception:
        logger.exception("baseline %s: a round did not start", held.pk)
        allocations.close_allocation(taken)
        return None


def give_up_stuck_runs(found: Round) -> None:
    if found.ended is None or timezone.now() < found.ended + RUNS_GIVEN_UP_AFTER:
        return
    bot_runs.fail([run for run in bot_runs.runs_of(found) if run.status not in bot_runs.OVER], "timed_out",
                  timezone.now())


def move_round(found: Round) -> None:
    if found.allocation.closed is None:
        allocations.heartbeat(found.allocation)
    lifecycle.catch_up(found)
    found.refresh_from_db()
    if found.phase == Phase.RUNNING.value and bot_runs.runs_over(found):
        found = lifecycle.end_round(found, BOTS_EXITED)
    if found.phase != Phase.ENDED.value:
        return
    lifecycle.judge_late(found)
    found.refresh_from_db()
    give_up_stuck_runs(found)
    records.keep_when_due(found)
    if RoundRecord.objects.filter(round_number=found.pk).exists() and found.allocation.closed is None:
        allocations.close_allocation(found.allocation)


def settle_status(held: BotBaseline) -> None:
    held.refresh_from_db()
    if len(held.samples) >= held.rounds_wanted:
        BotBaseline.objects.filter(problem_id=held.problem_id, human_side=held.human_side, step=held.step,
                                   status=CURRENT).exclude(pk=held.pk).update(status=STALE)
        BotBaseline.objects.filter(pk=held.pk).update(status=CURRENT)
        return
    if Round.objects.filter(baseline_of=held, allocation__closed=None).exists():
        return
    if held.attempts >= held.attempts_max:
        BotBaseline.objects.filter(pk=held.pk).update(status=FAILED)
        return
    open_next(held)


def latest_launcher() -> dict:
    run = BotRun.objects.exclude(launcher={}).order_by("-claimed", "-id").first()
    return dict(run.launcher) if run else {}


def expected_key(held: BotBaseline, launcher: dict) -> str:
    snapshot = content.snapshot(held.problem)
    return ranks.profile_key(records.profile_parts(snapshot, held.human_side, held.step, launcher))


def mark_stale() -> None:
    newest = latest_launcher()
    for held in BotBaseline.objects.filter(status=CURRENT).select_related("problem"):
        if held.profile_key != expected_key(held, newest or held.launcher):
            BotBaseline.objects.filter(pk=held.pk).update(status=STALE)


def advance() -> None:
    for held in BotBaseline.objects.filter(status=RUNNING).select_related("problem"):
        for found in Round.objects.filter(baseline_of=held, allocation__closed=None).select_related(
                "allocation", "baseline_of"):
            move_round(found)
        settle_status(held)
    mark_stale()


def line_of(held: BotBaseline) -> Line:
    return Line(baseline=held, spread=ranks.spread(held.samples))


def lines(problem_id: int) -> list[Line]:
    advance()
    return [line_of(held) for held in BotBaseline.objects.filter(problem_id=problem_id).order_by("id")]


def shown(line: Line) -> dict[str, Any]:
    held = line.baseline
    return {"baseline": held.pk, "human_side": held.human_side, "step": held.step, "status": held.status,
            "profile_key": held.profile_key, "counted": len(held.samples), "wanted": held.rounds_wanted,
            "attempted": held.attempts, "attempts_max": held.attempts_max, "exits": held.exits,
            "spread": {"n": line.spread.n, "low": line.spread.low, "median": line.spread.median,
                       "high": line.spread.high}}
