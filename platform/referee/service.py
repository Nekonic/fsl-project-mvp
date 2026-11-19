from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from cr import config, errors
from domain.scoring.correlate import correlate
from domain.scoring.metrics import ONE_CASE_ONE_DECISION, OriginActivity, free_actions, per_case
from domain.scoring.metrics import score as case_totals
from domain.scoring.objectives import ATTRIBUTION_WINDOW, CLOCK_SKEW, Attempt, attempts, attribute, breaches, tally
from domain.types import ActionRecord, DetectionRecord, ObjectiveRecord
from events import log
from match.models import Round
from range.runner import Runner
from referee import effect, loot
from referee.models import Objective

LOOT_VERIFIED = "loot_verified"
EFFECT_OBSERVED = "effect_observed"
KEPT, LOST = "kept", "lost"
PLACEHOLDER = "*"

Reach = Callable[[str], Runner]


@dataclass(frozen=True)
class ObjectiveState:
    key: str
    name: str
    state: str
    seen: bool


@dataclass(frozen=True)
class Fallen:
    key: str
    name: str
    difficulty: int


@dataclass(frozen=True)
class LootVerdict:
    fell: tuple[Fallen, ...]

    @property
    def lost(self) -> bool:
        return bool(self.fell)

    @property
    def objective(self) -> Fallen | None:
        return max(self.fell, key=lambda fallen: fallen.difficulty, default=None)


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


def objective_model(found: Round) -> str:
    return found.snapshot["wargame"]["objective_model"]


def secret(found: Round) -> Mapping[str, Any]:
    return found.snapshot["wargame"]["secret"]


def declared(found: Round) -> list[dict[str, Any]]:
    return list(found.snapshot.get("objectives") or [])


def tiers(found: Round) -> dict[str, list[dict[str, Any]]]:
    return {"tiers": [{"key": tier["key"], "name": tier["name"], "difficulty": tier["difficulty"], **tier["rule"]}
                      for tier in declared(found)]}


def ground_truth(wargame: Mapping[str, Any], reach: Reach | None = None) -> Any:
    held = wargame["secret"]
    if wargame["objective_model"] == LOOT_VERIFIED:
        inside = reach(held["role"]) if reach is not None else None
        return loot.baseline(dict(held), config.build().ground_truth, inside=inside)
    if reach is None:
        raise errors.Unavailable(code="ground_truth_unavailable")
    return effect.snapshot(reach(held["role"]))


def take_baseline(found: Round, reach: Reach | None = None) -> Any:
    baseline = ground_truth(found.snapshot["wargame"], reach)
    found.baseline = baseline
    found.save(update_fields=["baseline"])
    return baseline


def attempt_of(action: ActionRecord) -> Attempt:
    return Attempt(case_id=action.case_id or action.action_id, marker=action.marker, started_at=action.started_at,
                   ended_at=action.ended_at, malicious=action.malicious, detected=False, detection_ids=())


def lose(found: Round, fired: Iterable[Mapping[str, Any]], at: datetime, earliest: datetime | None,
         latest: datetime | None, marker: str | None) -> tuple[Fallen, ...]:
    fell = []
    with transaction.atomic():
        for tier in fired:
            _, created = Objective.objects.get_or_create(round=found, key=tier["key"], defaults={
                "name": tier["name"], "achieved_at": at, "earliest": earliest, "latest": latest,
                "attributed_marker": marker})
            if created:
                log.append(found.pk, "objective.lost",
                           {"key": tier["key"], "name": tier["name"], "attributed_marker": marker})
                fell.append(Fallen(key=tier["key"], name=tier["name"], difficulty=int(tier["difficulty"])))
    return tuple(fell)


def submit_loot(found: Round, value: Any, actions: Sequence[ActionRecord] = (),
                at: datetime | None = None) -> LootVerdict:
    if objective_model(found) != LOOT_VERIFIED:
        raise errors.Conflict(code="loot_not_taken")
    truth = found.baseline
    if not isinstance(truth, dict) or not truth:
        raise errors.Conflict(code="round_not_started")
    at = at or timezone.now()
    fired, _ = loot.tiers_fired(tiers(found), loot.matched(value, truth), truth)
    earliest, latest = at - ATTRIBUTION_WINDOW, at + CLOCK_SKEW
    credited = attribute(at, [attempt_of(action) for action in actions], earliest, latest)
    return LootVerdict(fell=lose(found, fired, at, earliest, latest, credited.marker if credited else None))


def window_of(at: datetime, actions: Sequence[ActionRecord]) -> ActionRecord | None:
    inside = [action for action in actions if action.malicious is not False
              and action.started_at - CLOCK_SKEW <= at <= action.ended_at + CLOCK_SKEW]
    return max(inside, key=lambda action: action.started_at, default=None)


def observe_effects(found: Round, reach: Reach, actions: Sequence[ActionRecord] = (),
                    now: datetime | None = None) -> tuple[Fallen, ...]:
    if objective_model(found) != EFFECT_OBSERVED or not found.baseline or found.started is None:
        return ()
    changes = effect.read_changes(reach(secret(found)["role"]), found.started)
    fell: list[Fallen] = []
    for tier, at in effect.credited(tiers(found), found.baseline, changes):
        window = window_of(at, actions)
        if window is None:
            continue
        fell += lose(found, [tier], at, window.started_at - CLOCK_SKEW, window.ended_at + CLOCK_SKEW, window.marker)
    found.read_of = {"effects_read_at": (now or timezone.now()).isoformat(), "changes": len(changes)}
    found.save(update_fields=["read_of"])
    return tuple(fell)


def losses(found: Round) -> dict[str, Objective]:
    return {objective.key: objective for objective in Objective.objects.filter(round=found)}


def objectives(found: Round) -> tuple[ObjectiveState, ...]:
    lost = losses(found)
    return tuple(ObjectiveState(key=tier["key"], name=tier["name"], state=LOST if tier["key"] in lost else KEPT,
                                seen=tier["key"] in lost and lost[tier["key"]].seen)
                 for tier in declared(found))


def variants(value: str) -> set[str]:
    escaped = json.dumps(value)[1:-1]
    return {value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value), escaped,
            escaped.replace("/", "\\/")} - {""}


def redact(text: str, truth: Mapping[str, Any]) -> str:
    hidden = {variant for value in truth.values() if isinstance(value, str) and value for variant in variants(value)}
    for variant in sorted(hidden, key=len, reverse=True):
        text = text.replace(variant, PLACEHOLDER * len(variant))
    return text


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
