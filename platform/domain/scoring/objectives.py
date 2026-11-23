from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.scoring.corroborate import corroborated, indiscriminate_signatures
from domain.types import (
    RESPONSE_ORIGIN,
    RESPONSE_VERSION,
    CaseRecord,
    CorrelationResult,
    DetectionRecord,
    ObjectiveRecord,
    ResponseRecord,
)

RESPONDED_WEIGHT = 0.5
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
    source_ip: str | None = None
    first_alert_at: datetime | None = None


@dataclass(frozen=True)
class Breach:
    key: str
    name: str
    category: str
    difficulty: int
    detected: bool
    responded: bool
    response_seconds: float | None
    attributed_marker: str | None
    detection_ids: tuple[str, ...]


@dataclass(frozen=True)
class Scoreboard:
    objectives: int
    difficulty_total: int
    detected: int
    responded: int
    coverage: float | None
    damage: float
    false_positives: int


def attempts(cases: Sequence[CaseRecord], result: CorrelationResult,
             detections: Sequence[DetectionRecord]) -> tuple[Attempt, ...]:
    signatures = {detection.detection_id: detection.signature for detection in detections}
    stamps = {detection.detection_id: detection.timestamp for detection in detections}
    noise = indiscriminate_signatures(result, signatures)
    made = []
    for case, match in zip(cases, result.matches, strict=True):
        shown = [signatures[one] for one in match.detection_ids if one in signatures]
        detected = match.detected and corroborated(case.expect, shown, noise) is not False
        made.append(Attempt(
            case_id=case.case_id,
            marker=case.marker,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=case.malicious,
            detected=detected,
            detection_ids=match.detection_ids if detected else (),
            source_ip=case.source_ip,
            first_alert_at=min((stamps[one] for one in match.detection_ids if one in stamps), default=None)
            if detected else None,
        ))
    return tuple(made)


def in_window(
    achieved_at: datetime,
    candidates: Sequence[Attempt],
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> tuple[Attempt, ...]:
    earliest = earliest or achieved_at - ATTRIBUTION_WINDOW
    latest = latest or achieved_at + CLOCK_SKEW
    return tuple(sorted(
        (attempt for attempt in candidates
         if attempt.malicious is not False and attempt.started_at <= latest and earliest <= attempt.ended_at),
        key=lambda attempt: attempt.started_at))


def attribute(
    achieved_at: datetime,
    candidates: Sequence[Attempt],
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> Attempt | None:
    inside = in_window(achieved_at, candidates, earliest, latest)
    return inside[-1] if inside else None


def first_alert(inside: Sequence[Attempt]) -> datetime | None:
    return min((attempt.first_alert_at for attempt in inside if attempt.first_alert_at), default=None)


def attack_markers(inside: Sequence[Attempt], replayed: frozenset[str]) -> set[str]:
    alerted = {attempt.marker for attempt in inside if attempt.detected and attempt.marker in replayed}
    if alerted:
        return alerted
    return {attempt.marker for attempt in inside if attempt.malicious and attempt.marker in replayed}


def refused_the_attack(response: ResponseRecord, inside: Sequence[Attempt]) -> bool:
    needed = attack_markers(inside, response.replayed)
    if needed:
        return needed <= response.refused
    return any(attempt.marker in response.refused for attempt in inside if attempt.marker)


def first_response(achieved_at: datetime, inside: Sequence[Attempt],
                   responses: Sequence[ResponseRecord]) -> datetime | None:
    if not inside:
        return None
    origins = {attempt.source_ip for attempt in inside if attempt.source_ip}
    after = first_alert(inside) or inside[0].started_at
    taken = [response.at for response in responses if response.at < achieved_at and (
        (response.kind == RESPONSE_ORIGIN and response.source_ip in origins)
        or (response.kind == RESPONSE_VERSION and after <= response.at and refused_the_attack(response, inside)))]
    return min(taken, default=None)


def breaches(objectives: Sequence[ObjectiveRecord], candidates: Sequence[Attempt],
             responses: Sequence[ResponseRecord] = ()) -> tuple[Breach, ...]:
    found = []
    for objective in objectives:
        if objective.achieved_at is None:
            continue
        inside = in_window(objective.achieved_at, candidates, objective.earliest, objective.latest)
        alerted = first_alert(inside)
        answered = first_response(objective.achieved_at, inside, responses)
        found.append(
            Breach(
                key=objective.key,
                name=objective.name,
                category=objective.category,
                difficulty=objective.difficulty,
                detected=any(attempt.detected for attempt in inside),
                responded=answered is not None,
                response_seconds=max(0.0, (answered - alerted).total_seconds()) if alerted and answered else None,
                attributed_marker=inside[-1].marker if inside else None,
                detection_ids=tuple(one for attempt in inside for one in attempt.detection_ids),
            )
        )
    return tuple(found)


def tally(lost: Sequence[Breach], false_positives: int) -> Scoreboard:
    total = sum(breach.difficulty for breach in lost)
    detected_difficulty = sum(breach.difficulty for breach in lost if breach.detected)
    responded_difficulty = sum(breach.difficulty for breach in lost if breach.responded)
    return Scoreboard(
        objectives=len(lost),
        difficulty_total=total,
        detected=sum(1 for breach in lost if breach.detected),
        responded=sum(1 for breach in lost if breach.responded),
        coverage=detected_difficulty / total if total else None,
        damage=total - responded_difficulty + RESPONDED_WEIGHT * responded_difficulty,
        false_positives=false_positives,
    )
