from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from domain.scoring.correlate import correlate
from domain.scoring.metrics import ONE_CASE_ONE_DECISION, OriginActivity, free_actions, per_case
from domain.scoring.metrics import score as case_totals
from domain.scoring.objectives import attempts, breaches, tally
from domain.types import ActionRecord, DetectionRecord, ObjectiveRecord
from scoring.baseline import LOOT_VERIFIED, declared, objective_model
from scoring.losses import losses
from scoring.models import Objective
from training.models import Round


@dataclass(frozen=True)
class LostObjective:
    key: str
    name: str
    seen: bool
    attributed_marker: str | None


@dataclass(frozen=True)
class KeptObjective:
    key: str
    name: str


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
    posture_drift: bool
    note: str = ONE_CASE_ONE_DECISION

    def shown(self) -> dict[str, Any]:
        return {
            "objectives": {"lost": [vars(one) for one in self.lost], "kept": [vars(one) for one in self.kept],
                           "weighted": self.weighted},
            "outcomes": {"per_case": [vars(line) for line in self.per_case], "totals": vars(self.totals),
                         "note": self.note},
            "free_actions": {"by_origin": [vars(origin) for origin in self.free_actions]},
            "posture_drift": self.posture_drift,
        }


def record_of(tier: Mapping[str, Any], row: Objective | None, by_loot: bool) -> ObjectiveRecord:
    return ObjectiveRecord(key=tier["key"], name=tier["name"], category=tier.get("category") or "",
                           difficulty=int(tier["difficulty"]), achieved_at=row.achieved_at if row else None,
                           earliest=row.earliest if row else None, latest=row.latest if row else None,
                           by_loot=by_loot)


def objective_records(found: Round) -> tuple[ObjectiveRecord, ...]:
    lost = losses(found)
    by_loot = objective_model(found) == LOOT_VERIFIED
    return tuple(record_of(tier, lost.get(tier["key"]), by_loot) for tier in declared(found))


def score(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord],
          correlation: str | None = None, posture_drift: bool = False) -> RoundScore:
    cases = [action.as_case() for action in actions]
    result = correlate(cases, detections, correlation)
    totals = case_totals(result)
    records = objective_records(found)
    lost = breaches(records, attempts(cases, result))
    fallen = {breach.key for breach in lost}
    return RoundScore(
        lost=tuple(LostObjective(key=breach.key, name=breach.name, seen=breach.detected,
                                 attributed_marker=breach.attributed_marker) for breach in lost),
        kept=tuple(KeptObjective(key=record.key, name=record.name) for record in records if record.key not in fallen),
        weighted=tally(lost, totals.fp).damage,
        per_case=tuple(CaseLine(case=outcome.case_id, verdict=outcome.verdict, alerts=outcome.alerts,
                                corroborated=outcome.corroborated)
                       for outcome in per_case(result, cases, detections)),
        totals=Totals(tp=totals.tp, fp=totals.fp, fn=totals.fn, tn=totals.tn),
        free_actions=free_actions(result, cases, detections),
        posture_drift=posture_drift,
    )


def settle(found: Round, actions: Sequence[ActionRecord], detections: Sequence[DetectionRecord]) -> int:
    settled = {one.key: one for one in score(found, actions, detections).lost}
    changed = 0
    for objective in Objective.objects.filter(round=found, key__in=settled):
        now = settled[objective.key]
        if (objective.seen, objective.attributed_marker) != (now.seen, now.attributed_marker):
            objective.seen, objective.attributed_marker = now.seen, now.attributed_marker
            objective.save(update_fields=["seen", "attributed_marker"])
            changed += 1
    return changed
