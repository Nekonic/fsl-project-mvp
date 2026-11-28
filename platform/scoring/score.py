from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from domain.scoring.correlate import correlate
from domain.scoring.metrics import ONE_CASE_ONE_DECISION, OriginActivity, decided, free_actions, per_case
from domain.scoring.metrics import score as case_totals
from domain.scoring.objectives import attempts, breaches, tally
from domain.types import ActionRecord, DetectionRecord, ObjectiveRecord, ResponseRecord
from scoring.baseline import LOOT_VERIFIED, declared, objective_model
from scoring.losses import losses
from scoring.models import ObjectiveLoss, Verdict
from training.models import Round


@dataclass(frozen=True)
class LostObjective:
    key: str
    name: str
    difficulty: int
    detected: bool
    responded: bool
    response_seconds: float | None
    attributed_marker: str | None


@dataclass(frozen=True)
class KeptObjective:
    key: str
    name: str
    difficulty: int


@dataclass(frozen=True)
class CaseLine:
    case: str
    verdict: str
    alerts: int
    corroborated: bool | None


@dataclass(frozen=True)
class Totals:
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass(frozen=True)
class RoundScore:
    lost: tuple[LostObjective, ...]
    kept: tuple[KeptObjective, ...]
    weighted: float
    per_case: tuple[CaseLine, ...]
    totals: Totals
    free_actions: tuple[OriginActivity, ...]
    note: str = ONE_CASE_ONE_DECISION

    def shown(self) -> dict[str, Any]:
        return {
            "objectives": {"lost": [vars(one) for one in self.lost], "kept": [vars(one) for one in self.kept],
                           "weighted": self.weighted},
            "outcomes": {"per_case": [vars(line) for line in self.per_case], "totals": vars(self.totals),
                         "note": self.note},
            "free_actions": {"by_origin": [vars(origin) for origin in self.free_actions]},
        }


def record_of(tier: Mapping[str, Any], row: ObjectiveLoss | None, by_loot: bool) -> ObjectiveRecord:
    return ObjectiveRecord(key=tier["key"], name=tier["name"], category=tier.get("category") or "",
                           difficulty=int(tier["difficulty"]), achieved_at=row.achieved_at if row else None,
                           earliest=row.earliest if row else None, latest=row.latest if row else None,
                           by_loot=by_loot)


def until(found: Round) -> datetime | None:
    return found.ended


def objective_records(found: Round) -> tuple[ObjectiveRecord, ...]:
    end = until(found)
    lost = {key: row for key, row in losses(found).items() if end is None or row.achieved_at <= end}
    by_loot = objective_model(found) == LOOT_VERIFIED
    return tuple(record_of(tier, lost.get(tier["key"]), by_loot) for tier in declared(found))


def up_to_the_end(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord]
                  ) -> tuple[list[ActionRecord], list[DetectionRecord]]:
    end = until(found)
    return ([action for action in actions if end is None or action.started_at <= end],
            [detection for detection in detections if end is None or detection.timestamp <= end])


def score(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord],
          correlation: str | None = None, responses: Sequence[ResponseRecord] = ()) -> RoundScore:
    actions, detections = up_to_the_end(found, actions, detections)
    cases = [action.as_case() for action in actions]
    result = correlate(cases, detections, correlation)
    totals = case_totals(result)
    records = objective_records(found)
    lost = breaches(records, attempts(cases, result, detections), responses)
    fallen = {breach.key for breach in lost}
    return RoundScore(
        lost=tuple(LostObjective(key=breach.key, name=breach.name, difficulty=breach.difficulty,
                                 detected=breach.detected,
                                 responded=breach.responded, response_seconds=breach.response_seconds,
                                 attributed_marker=breach.attributed_marker) for breach in lost),
        kept=tuple(KeptObjective(key=record.key, name=record.name, difficulty=record.difficulty)
                   for record in records if record.key not in fallen),
        weighted=tally(lost, totals.fp).damage,
        per_case=tuple(CaseLine(case=outcome.case_id, verdict=outcome.verdict, alerts=outcome.alerts,
                                corroborated=outcome.corroborated)
                       for outcome in per_case(result, cases, detections)),
        totals=Totals(tp=totals.tp, fp=totals.fp, fn=totals.fn, tn=totals.tn),
        free_actions=free_actions(result, cases, detections),
    )


def settle(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord],
           responses: Sequence[ResponseRecord] = ()) -> int:
    settled = {one.key: one for one in score(found, actions, detections, responses=responses).lost}
    changed = 0
    for objective in ObjectiveLoss.objects.filter(round=found, key__in=settled):
        now = settled[objective.key]
        if (objective.seen, objective.attributed_marker) != (now.detected, now.attributed_marker):
            objective.seen, objective.attributed_marker = now.detected, now.attributed_marker
            objective.save(update_fields=["seen", "attributed_marker"])
            changed += 1
    return changed


def judge(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord],
          running: set[str], now: datetime, wait: timedelta) -> list[Verdict]:
    actions, detections = up_to_the_end(found, actions, detections)
    cases = [action.as_case() for action in actions]
    declared = [action for action, case in zip(actions, cases) if case.declared]
    already = set(Verdict.objects.filter(round=found).values_list("action", flat=True))
    made: list[Verdict] = []
    for action, outcome in zip(declared, per_case(correlate(cases, detections), cases, detections)):
        if action.action_id in already or not decided(outcome, action.ended_at, now, wait,
                                                      running=action.action_id in running,
                                                      round_over=found.ended is not None):
            continue
        row, created = Verdict.objects.get_or_create(round=found, action=action.action_id, defaults={
            "case": outcome.case_id, "verdict": outcome.verdict, "alerts": outcome.alerts,
            "corroborated": outcome.corroborated, "judged_at": now})
        if created:
            made.append(row)
    return made
