from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from cr import errors
from domain.scoring.objectives import ATTRIBUTION_WINDOW, CLOCK_SKEW, Attempt, attribute
from domain.types import ActionRecord
from scoring import effect, loot
from scoring.baseline import EFFECT_OBSERVED, LOOT_VERIFIED, Reach, declared, objective_model, secret, tiers
from scoring.models import Objective
from telemetry import events as log
from training.models import Round

KEPT, LOST = "kept", "lost"


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


def window_of(at: datetime, actions: Sequence[ActionRecord]) -> tuple[ActionRecord, ...]:
    return tuple(sorted((action for action in actions if action.malicious is not False
                         and action.started_at - CLOCK_SKEW <= at <= action.ended_at + CLOCK_SKEW),
                        key=lambda action: action.started_at))


def observe_effects(found: Round, reach: Reach, actions: Sequence[ActionRecord] = (),
                    now: datetime | None = None) -> tuple[Fallen, ...]:
    if objective_model(found) != EFFECT_OBSERVED or not found.baseline or found.started is None:
        return ()
    changes = effect.read_changes(reach(secret(found)["role"]), found.started)
    fell: list[Fallen] = []
    for tier, at in effect.credited(tiers(found), found.baseline, changes):
        if at < found.started or (found.ends_at and at > found.ends_at):
            continue
        window = window_of(at, actions)
        if not window:
            fell += lose(found, [tier], at, at - CLOCK_SKEW, at + CLOCK_SKEW, None)
            continue
        fell += lose(found, [tier], at, window[0].started_at - CLOCK_SKEW,
                     max(action.ended_at for action in window) + CLOCK_SKEW, window[-1].marker)
    found.read_of = {"effects_read_at": (now or timezone.now()).isoformat(), "changes": len(changes)}
    found.save(update_fields=["read_of"])
    return tuple(fell)


def fallen_on(allocation_id: int) -> bool:
    return Objective.objects.filter(round__allocation_id=allocation_id).exists()


def losses(found: Round) -> dict[str, Objective]:
    return {objective.key: objective for objective in Objective.objects.filter(round=found)}


def objectives(found: Round) -> tuple[ObjectiveState, ...]:
    lost = losses(found)
    return tuple(ObjectiveState(key=tier["key"], name=tier["name"], state=LOST if tier["key"] in lost else KEPT,
                                seen=tier["key"] in lost and lost[tier["key"]].seen)
                 for tier in declared(found))
