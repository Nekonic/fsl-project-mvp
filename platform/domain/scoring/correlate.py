from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from domain.types import (
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
    strategy: str | None = None,
) -> CorrelationResult:
    if strategy is not None:
        _require_known(strategy, "the forced strategy")
        cases = [replace(case, correlation=strategy) for case in cases]
    for case in cases:
        _require_known(case.correlation, f"case {case.case_id!r}")

    matches: list[CaseMatch] = []
    matched: set[str] = set()
    for case in cases:
        hits = tuple(d.detection_id for d in detections if matches_case(case, d))
        matched.update(hits)
        matches.append(
            CaseMatch(
                case_id=case.case_id,
                name=case.name,
                malicious=case.malicious,
                detection_ids=hits,
                detected=bool(hits),
            )
        )

    return CorrelationResult(
        matches=tuple(matches),
        unmatched_detection_ids=tuple(d.detection_id for d in detections if d.detection_id not in matched),
        warnings=_warnings(cases, detections),
    )


def matches_case(case: CaseRecord, detection: DetectionRecord) -> bool:
    if case.correlation == CORRELATION_MARKER:
        return detection.marker is not None and detection.marker == case.marker and _sent_from(case, detection)
    if case.source_ip is None or detection.src_ip != case.source_ip:
        return False
    if detection.marker not in (None, case.marker):
        return False
    if case.path and detection.uri and detection.uri != case.path:
        return False
    return case.started_at - WINDOW_SLACK <= detection.timestamp <= case.ended_at + WINDOW_SLACK


def _sent_from(case: CaseRecord, detection: DetectionRecord) -> bool:
    return case.source_ip is None or detection.src_ip is None or detection.src_ip == case.source_ip


def _require_known(strategy: str, whose: str) -> None:
    if strategy not in CORRELATION_STRATEGIES:
        raise ValueError(
            f"unknown correlation strategy {strategy!r} for {whose}; expected one of {CORRELATION_STRATEGIES}"
        )


def _warnings(cases: Sequence[CaseRecord], detections: Sequence[DetectionRecord]) -> tuple[tuple[str, ...], ...]:
    warnings: list[tuple[str, ...]] = []
    if any(c.correlation == CORRELATION_MARKER for c in cases) and detections and not any(d.marker for d in detections):
        warnings.append(("no_marker",))
    missing_ip = [c.name for c in cases if c.correlation == CORRELATION_WINDOW and c.source_ip is None]
    if missing_ip:
        warnings.append(("no_source_ip", ", ".join(missing_ip)))
    return tuple(warnings)
