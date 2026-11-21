from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.types import CaseRecord, CorrelationResult, ObjectiveRecord

DETECTED_WEIGHT = 0.5
ATTRIBUTION_WINDOW = timedelta(minutes=2)
CLOCK_SKEW = timedelta(milliseconds=100)


@dataclass(frozen=True)
class Attempt:
    case_id: str
    marker: str | None
    started_at: datetime
    ended_at: datetime
    malicious: bool | None
    detected: bool
    detection_ids: tuple[str, ...]


@dataclass(frozen=True)
class Breach:
    key: str
    name: str
    category: str
    difficulty: int
    detected: bool
    attributed_marker: str | None
    detection_ids: tuple[str, ...]


@dataclass(frozen=True)
class Scoreboard:
    objectives: int
    difficulty_total: int
    detected: int
    undetected: int
    detected_difficulty: int
    undetected_difficulty: int
    coverage: float | None
    damage: float
    false_positives: int


def attempts(cases: Sequence[CaseRecord], result: CorrelationResult) -> tuple[Attempt, ...]:
    return tuple(
        Attempt(
            case_id=case.case_id,
            marker=case.marker,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=case.malicious,
            detected=match.detected,
            detection_ids=match.detection_ids,
        )
        for case, match in zip(cases, result.matches, strict=True)
    )


def attribute(
    achieved_at: datetime,
    candidates: Sequence[Attempt],
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> Attempt | None:
    earliest = earliest or achieved_at - ATTRIBUTION_WINDOW
    latest = latest or achieved_at + CLOCK_SKEW
    eligible = [
        attempt
        for attempt in candidates
        if attempt.malicious is not False and attempt.started_at <= latest and earliest <= attempt.ended_at
    ]
    return max(eligible, key=lambda attempt: attempt.started_at, default=None)


def breaches(objectives: Sequence[ObjectiveRecord], candidates: Sequence[Attempt]) -> tuple[Breach, ...]:
    found = []
    for objective in objectives:
        if objective.achieved_at is None:
            continue
        credited = attribute(objective.achieved_at, candidates, objective.earliest, objective.latest)
        found.append(
            Breach(
                key=objective.key,
                name=objective.name,
                category=objective.category,
                difficulty=objective.difficulty,
                detected=bool(credited and credited.detected),
                attributed_marker=credited.marker if credited else None,
                detection_ids=credited.detection_ids if credited else (),
            )
        )
    return tuple(found)


def tally(lost: Sequence[Breach], false_positives: int) -> Scoreboard:
    detected = [b for b in lost if b.detected]
    missed = [b for b in lost if not b.detected]
    detected_difficulty = sum(b.difficulty for b in detected)
    undetected_difficulty = sum(b.difficulty for b in missed)
    total = detected_difficulty + undetected_difficulty
    return Scoreboard(
        objectives=len(lost),
        difficulty_total=total,
        detected=len(detected),
        undetected=len(missed),
        detected_difficulty=detected_difficulty,
        undetected_difficulty=undetected_difficulty,
        coverage=detected_difficulty / total if total else None,
        damage=undetected_difficulty + DETECTED_WEIGHT * detected_difficulty,
        false_positives=false_positives,
    )
