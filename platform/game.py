from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

FAST = timedelta(seconds=10)
SLOW = timedelta(seconds=120)

WEIGHTS = {"speed": 0.30, "accuracy": 0.40, "coverage": 0.30}

FALSE_POSITIVE_COST = 1.0
DETECTED_TAKE = 0.5


@dataclass(frozen=True)
class Attempt:
    case_id: str
    malicious: bool
    stage: str
    started_at: datetime
    detected_at: datetime | None


@dataclass(frozen=True)
class Taken:
    key: str
    difficulty: int
    detected: bool


@dataclass(frozen=True)
class GameScore:
    balance: float
    attacker: float
    defender: float
    speed: float
    accuracy: float
    coverage: float
    response: float | None
    weights: dict


def _speed_credit(attempt: Attempt) -> float:
    if attempt.detected_at is None:
        return 0.0
    delay = (attempt.detected_at - attempt.started_at).total_seconds()
    fast, slow = FAST.total_seconds(), SLOW.total_seconds()
    if delay <= fast:
        return 1.0
    if delay >= slow:
        return 0.0
    return 1.0 - (delay - fast) / (slow - fast)


def speed(attempts: list[Attempt]) -> float:
    malicious = [a for a in attempts if a.malicious]
    if not malicious:
        return 0.0
    return sum(_speed_credit(a) for a in malicious) / len(malicious)


def coverage(attempts: list[Attempt]) -> float:
    attacked = {a.stage for a in attempts if a.malicious and a.stage}
    if not attacked:
        return 0.0
    seen = {a.stage for a in attempts if a.malicious and a.stage and a.detected_at is not None}
    return len(seen) / len(attacked)


def accuracy(tp: int, fp: int, fn: int, tn: int) -> float:
    recall = tp / (tp + fn) if tp + fn else 0.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    return max(0.0, recall - false_positive_rate)


def attacker_take(taken: list[Taken]) -> float:
    return sum(t.difficulty * (DETECTED_TAKE if t.detected else 1.0) for t in taken)


def settle(
    attempts: list[Attempt],
    taken: list[Taken],
    tp: int,
    fp: int,
    fn: int,
    tn: int,
) -> GameScore:
    pillars = {
        "speed": speed(attempts),
        "accuracy": accuracy(tp, fp, fn, tn),
        "coverage": coverage(attempts),
    }
    at_stake = sum(t.difficulty for t in taken)
    quality = sum(WEIGHTS[name] * value for name, value in pillars.items())

    attacker = attacker_take(taken)
    defender = quality * at_stake - FALSE_POSITIVE_COST * fp

    return GameScore(
        balance=defender - attacker,
        attacker=attacker,
        defender=defender,
        speed=pillars["speed"],
        accuracy=pillars["accuracy"],
        coverage=pillars["coverage"],
        response=None,
        weights=dict(WEIGHTS),
    )
