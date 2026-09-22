from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from scoring.types import (
    CORRELATION_MARKER,
    CORRELATION_STRATEGIES,
    CORRELATION_WINDOW,
    CaseMatch,
    CaseRecord,
    CorrelationResult,
    DetectionRecord,
)

WINDOW_SLACK = timedelta(seconds=2)

def correlate(
    cases: Sequence[CaseRecord],
    detections: Sequence[DetectionRecord],
) -> CorrelationResult:
    for case in cases:
        if case.correlation not in CORRELATION_STRATEGIES:
            raise ValueError(
                f"unknown correlation strategy {case.correlation!r} "
                f"for case {case.case_id!r}; expected one of {CORRELATION_STRATEGIES}"
            )

    matches: list[CaseMatch] = []
    matched_detection_ids: set[str] = set()

    for case in cases:
        hits = tuple(d.detection_id for d in detections if _matches(case, d))
        matched_detection_ids.update(hits)
        matches.append(
            CaseMatch(
                case_id=case.case_id,
                name=case.name,
                malicious=case.malicious,
                detection_ids=hits,
                detected=bool(hits),
            )
        )

    unmatched = tuple(
        d.detection_id for d in detections if d.detection_id not in matched_detection_ids
    )

    return CorrelationResult(
        matches=tuple(matches),
        unmatched_detection_ids=unmatched,
        warnings=_warnings(cases, detections),
    )

def _matches(case: CaseRecord, detection: DetectionRecord) -> bool:
    if case.correlation == CORRELATION_MARKER:
        return detection.marker is not None and detection.marker == case.case_id

    if case.source_ip is None or detection.src_ip != case.source_ip:
        return False
    return (
        case.started_at - WINDOW_SLACK
        <= detection.timestamp
        <= case.ended_at + WINDOW_SLACK
    )

def _warnings(
    cases: Sequence[CaseRecord],
    detections: Sequence[DetectionRecord],
) -> tuple[tuple[str, ...], ...]:
    warnings: list[tuple[str, ...]] = []

    marker_cases = [c for c in cases if c.correlation == CORRELATION_MARKER]
    if marker_cases and detections and not any(d.marker for d in detections):
        warnings.append(("score.warning.no_marker",))

    missing_ip = [
        c.name
        for c in cases
        if c.correlation == CORRELATION_WINDOW and c.source_ip is None
    ]
    if missing_ip:
        warnings.append(("score.warning.no_source_ip", ", ".join(missing_ip)))

    return tuple(warnings)
