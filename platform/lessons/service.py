from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from attack import service as attack
from content import service as content
from cr import errors
from defence import service as defence
from domain import checks
from events import log
from lessons import facts
from lessons.models import Progress, StepResult
from match import service as match
from referee import service as referee

WAITING_SLOT, STARTING, READY, ENDED = "waiting_slot", "starting", "ready", "ended"
PHASES = (WAITING_SLOT, STARTING, READY, ENDED)
STEPS_DONE = "steps_done"
ENDED_BY_LEARNER = "ended_by_operator"


@dataclass(frozen=True)
class StepLine:
    order: int
    body: str
    opens: str
    hints_available: int


@dataclass(frozen=True)
class Brief:
    id: int
    side: str
    title: str
    summary: str
    body: str


@dataclass(frozen=True)
class Standing:
    passed_order: int
    passed_at: datetime | None


@dataclass(frozen=True)
class Lesson:
    round: int
    lease: int
    phase: str
    problem: Brief
    steps: tuple[StepLine, ...]
    current: int | None
    progress: Standing


@dataclass(frozen=True)
class LessonLine:
    round: int
    problem: int
    phase: str
    passed_order: int


@dataclass(frozen=True)
class Checked:
    verdict: str
    detail_code: str | None
    next: int | None


@dataclass(frozen=True)
class Hint:
    hint: str
    n: int
    left: int


def lesson_problem(user, problem_id: int):
    found = content.problem(problem_id) if user.is_staff else content.published_problem(problem_id)
    if found.kind != match.LESSON:
        raise errors.Invalid(code="invalid_choice", path="problem")
    return found


def advanced(found):
    if found.phase == match.CREATED and match.ready(found.lease):
        try:
            match.start_round(found)
        except (errors.Unavailable, errors.Conflict):
            pass
        found.refresh_from_db()
    return found


def open_lesson(user, problem_id: int) -> Lesson:
    problem = lesson_problem(user, problem_id)
    held = match.open_lease(user, problem.wargame_id, match.LESSON)
    try:
        found = match.create_lesson_round(held, problem.pk, user)
    except errors.DomainError:
        match.close_lease(held)
        raise
    return shown(advanced(found))


def learner_of(found):
    seated = match.seats(found)
    return seated[0].user if seated else None


def lesson_of(round_id: int, user, reading: bool = False):
    found = match.round_of(round_id)
    if found.kind != match.LESSON:
        raise errors.NotFound(code="unknown_round")
    holder = learner_of(found)
    if holder is None or holder.pk != user.pk:
        if not (reading and user.is_staff):
            raise errors.NotSeated()
    return found


def phase_of(found) -> str:
    if found.phase == match.ENDED:
        return ENDED
    if found.phase == match.RUNNING:
        return READY
    if found.phase == match.CREATED and not match.ready(found.lease):
        return WAITING_SLOT
    return STARTING


def steps_of(found) -> list[dict[str, Any]]:
    frozen = found.snapshot or content.snapshot(found.problem)
    return sorted(frozen.get("steps") or [], key=lambda step: step["order"])


def step_of(steps: list[dict[str, Any]], order: int) -> dict[str, Any]:
    chosen = next((step for step in steps if step["order"] == order), None)
    if chosen is None:
        raise errors.NotFound(code="unknown_step")
    return chosen


def standing(user, problem_id: int) -> Standing:
    found = Progress.objects.filter(user=user, problem_id=problem_id).first() if user is not None else None
    return Standing(passed_order=found.passed_order, passed_at=found.passed_at) if found else Standing(0, None)


def current_of(steps: list[dict[str, Any]], passed_order: int) -> int | None:
    return next((step["order"] for step in steps if step["order"] > passed_order), None)


def brief_of(found) -> Brief:
    problem = (found.snapshot or {}).get("problem") or {}
    source = found.problem
    return Brief(id=found.problem_id, side=problem.get("side", source.side), title=problem.get("title", source.title),
                 summary=problem.get("summary", source.summary), body=problem.get("body", source.body))


def shown(found) -> Lesson:
    steps = steps_of(found)
    progress = standing(learner_of(found), found.problem_id)
    return Lesson(round=found.pk, lease=found.lease_id, phase=phase_of(found), problem=brief_of(found),
                  steps=tuple(StepLine(order=step["order"], body=step["body"], opens=step["opens"],
                                       hints_available=len(step.get("hints") or [])) for step in steps),
                  current=current_of(steps, progress.passed_order), progress=progress)


def lesson(round_id: int, user) -> Lesson:
    return shown(advanced(lesson_of(round_id, user, reading=True)))


def lessons_for(user) -> list[LessonLine]:
    found = [one for one in match.rounds_for(user, mine=True) if one.kind == match.LESSON]
    return [LessonLine(round=one.pk, problem=one.problem_id, phase=phase_of(one),
                       passed_order=standing(user, one.problem_id).passed_order) for one in found]


def unlocked(found, user, order: int) -> dict[str, Any]:
    steps = steps_of(found)
    chosen = step_of(steps, order)
    if order > (current_of(steps, standing(user, found.problem_id).passed_order) or order):
        raise errors.Conflict(code="step_locked")
    return chosen


def running(found) -> None:
    if found.phase == match.ENDED:
        raise errors.Conflict(code="round_closed")
    if found.phase != match.RUNNING:
        raise errors.Conflict(code="round_not_started")


def seat_on(found, side: str):
    return next((seat for seat in match.seats(found) if seat.side == side), None)


def readers(found, seat=None) -> facts.Readers:
    return facts.Readers(
        latest_test=lambda engine: defence.latest_table(found, engine, seat),
        applied=lambda: defence.applied_by_seats(found),
        detections=lambda: defence.detections(found),
        actions=lambda: attack.actions(found),
        commands=lambda: attack.commands(found),
        objectives=lambda: referee.objective_records(found),
        waf_before=lambda at: defence.tuning_at(found, at) if at else defence.start_tuning(found),
        waf_after=lambda: defence.tuning_at(found),
    )


def opened_at(found, order: int) -> datetime:
    earlier = [step["order"] for step in steps_of(found) if step["order"] < order]
    if not earlier:
        return found.started
    first = StepResult.objects.filter(round=found, verdict=checks.PASSED, step_order=max(earlier)).order_by("at").first()
    return max(found.started, first.at) if first else found.started


def judged(step: dict[str, Any], answer: Any, reached: facts.Readers, opened: datetime | None) -> checks.Verdict:
    kind, spec = step["check"]["kind"], step["check"].get("params") or {}
    return checks.judge(kind, spec, answer, facts.gather(kind, reached, opened))


def passed(user, found, order: int) -> None:
    with transaction.atomic():
        progress, _ = Progress.objects.select_for_update().get_or_create(user=user, problem_id=found.problem_id)
        if order > progress.passed_order:
            progress.passed_order, progress.passed_at = order, timezone.now()
            progress.save(update_fields=["passed_order", "passed_at"])


def check(round_id: int, user, order: int, answer: Any = None) -> Checked:
    found = lesson_of(round_id, user)
    step = unlocked(found, user, order)
    running(found)
    verdict = judged(step, answer, readers(found, seat_on(found, "defence")), opened_at(found, order))
    StepResult.objects.create(round=found, step_order=order, verdict=verdict.outcome, given=answer)
    log.append(found.pk, "step.answered", {"order": order, "verdict": verdict.outcome})
    if not verdict.passed:
        return Checked(verdict=verdict.outcome, detail_code=verdict.detail_code, next=None)
    log.append(found.pk, "step.passed", {"order": order})
    passed(user, found, order)
    following = current_of(steps_of(found), standing(user, found.problem_id).passed_order)
    if following is None:
        match.close_lease(found.lease, STEPS_DONE)
    return Checked(verdict=verdict.outcome, detail_code=None, next=following)


def hint(round_id: int, user, order: int, n: int) -> Hint:
    found = lesson_of(round_id, user)
    hints = list(unlocked(found, user, order).get("hints") or [])
    if n < 1:
        raise errors.Invalid(code="min_value", path="n")
    if n > len(hints):
        raise errors.Invalid(code="max_value", path="n", params={"max": len(hints)})
    return Hint(hint=hints[n - 1], n=n, left=len(hints) - n)


def end(round_id: int, user):
    found = lesson_of(round_id, user)
    match.close_lease(found.lease, ENDED_BY_LEARNER)
    found.refresh_from_db()
    return found


def try_step(problem_id: int, order: int, round_id: int, answer: Any = None) -> Checked:
    problem = content.problem(problem_id)
    step = step_of(sorted(content.snapshot(problem)["steps"], key=lambda one: one["order"]), order)
    found = match.round_of(round_id)
    if found.lease.wargame_id != problem.wargame_id:
        raise errors.Invalid(code="invalid_choice", path="round")
    if found.phase != match.ENDED:
        raise errors.Conflict(code="round_running")
    verdict = judged(step, answer, readers(found), None)
    return Checked(verdict=verdict.outcome, detail_code=verdict.detail_code, next=None)
