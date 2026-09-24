from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DETECTED_WEIGHT = 0.5

ATTRIBUTION_WINDOW = timedelta(minutes=2)

CLOCK_SKEW = timedelta(milliseconds=100)

def corroborated(expect: str | None, signatures, indiscriminate=()) -> bool | None:
    if not expect:
        return None
    needle = expect.lower()
    discriminating = [s for s in signatures if s not in indiscriminate]
    return any(needle in signature.lower() for signature in discriminating)

@dataclass(frozen=True)
class Attempt:

    case_id: str
    started_at: datetime
    ended_at: datetime
    malicious: bool
    detected: bool
    detection_ids: tuple[str, ...]

def attribute(
    achieved_at: datetime,
    attempts: list[Attempt],
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> Attempt | None:
    earliest = earliest or achieved_at - ATTRIBUTION_WINDOW
    latest = latest or achieved_at + CLOCK_SKEW
    candidates = [
        attempt
        for attempt in attempts
        if attempt.malicious
        and attempt.started_at <= latest
        and earliest <= attempt.ended_at
    ]
    return max(candidates, key=lambda attempt: attempt.started_at, default=None)

@dataclass(frozen=True)
class Breach:

    key: str
    name: str
    category: str
    difficulty: int
    detected: bool
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

def tally(breaches: list[Breach], false_positives: int) -> Scoreboard:
    detected = [b for b in breaches if b.detected]
    missed = [b for b in breaches if not b.detected]

    detected_difficulty = sum(b.difficulty for b in detected)
    undetected_difficulty = sum(b.difficulty for b in missed)
    total = detected_difficulty + undetected_difficulty

    return Scoreboard(
        objectives=len(breaches),
        difficulty_total=total,
        detected=len(detected),
        undetected=len(missed),
        detected_difficulty=detected_difficulty,
        undetected_difficulty=undetected_difficulty,
        coverage=detected_difficulty / total if total else None,
        damage=undetected_difficulty + DETECTED_WEIGHT * detected_difficulty,
        false_positives=false_positives,
    )
