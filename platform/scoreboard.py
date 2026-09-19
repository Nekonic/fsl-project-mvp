"""What the two sides actually achieved. Pure functions, no I/O.

The scoring shape is the one cyber defence exercises settled on: losing an
objective always costs, and detecting the attack that took it costs less. CCDC
states it directly - an incident report that correctly identifies a red team
attack reduces that event's penalty, and no partial credit is given for a vague
one. Detection is mitigation, not the game.

False positives stay separate and are never traded against breaches. A defence
that sees every attack by alerting on everything has not defended anything, and
a single blended number would let it look as though it had.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# What a detected breach costs against an undetected one. Half, because being
# breached and knowing is materially better than being breached and not
# knowing, and not because the number has been tuned against anything.
DETECTED_WEIGHT = 0.5


# How long after a case started an objective may still be credited to it.
# Objectives are noticed by polling the target, so the moment of observation
# trails the moment of the deed by up to one poll interval. Requiring the
# observed time to land inside a case's own window - which is often a tenth of
# a second wide - would attribute almost nothing to anybody.
ATTRIBUTION_WINDOW = timedelta(minutes=2)


def corroborated(expect: str | None, signatures) -> bool | None:
    """Whether the evidence matches the attack's own mechanism.

    A true positive says only that something fired inside the window. It does
    not say the alert had anything to do with the attack. Mahoney and Chan
    (RAID 2003) built a detector that scored with the best systems of the 1999
    DARPA evaluation by reading one byte of the source address, and fell to
    zero detections once real traffic was mixed in: right, for the wrong
    reason, and the score could not tell.

    So a case declares what should be able to detect it, and this asks whether
    anything attributed to it says so. `None` means the case declared nothing -
    a terminal window, say - which is not the same as False.
    """
    if not expect:
        return None
    needle = expect.lower()
    return any(needle in signature.lower() for signature in signatures)


@dataclass(frozen=True)
class Attempt:
    """One case the red team fired, and what the defence made of it."""

    case_id: str
    started_at: datetime
    detected: bool
    detection_ids: tuple[str, ...]


def attribute(achieved_at: datetime, attempts: list[Attempt]) -> Attempt | None:
    """Which attempt an objective is credited to: the last one before it.

    Not the enclosing window, for the reason above. An objective nobody was
    attacking at the time belongs to nobody, and is reported as undetected -
    which is the honest answer, because no alert was tied to it either.
    """
    candidates = [
        attempt
        for attempt in attempts
        if attempt.started_at <= achieved_at <= attempt.started_at + ATTRIBUTION_WINDOW
    ]
    return max(candidates, key=lambda attempt: attempt.started_at, default=None)


@dataclass(frozen=True)
class Breach:
    """One objective the red team reached, and whether the defence saw it."""

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
    coverage: float
    damage: float
    false_positives: int


def tally(breaches: list[Breach], false_positives: int) -> Scoreboard:
    """Score a session.

    `coverage` is the share of damage the defence saw, weighted by difficulty:
    missing one six-star breach is worse than missing one one-star breach, and
    counting breaches rather than weight would hide that.
    """
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
        # An untouched session is not a failure to detect anything.
        coverage=detected_difficulty / total if total else 1.0,
        damage=undetected_difficulty + DETECTED_WEIGHT * detected_difficulty,
        false_positives=false_positives,
    )
