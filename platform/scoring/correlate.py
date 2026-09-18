"""케이스(ground truth)와 경보를 대응시킨다. 순수 함수만 있다."""

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
    """케이스마다 어떤 경보가 걸렸는지 판정한다.

    케이스는 자기가 선언한 전략 하나만 쓴다. 마커 케이스는 시각·IP 를 보지
    않고, 시간창 케이스는 마커를 보지 않는다. 폴백을 허용하면 파이프라인
    고장이 탐지 성공으로 둔갑한다.
    """
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
) -> tuple[str, ...]:
    warnings: list[str] = []

    marker_cases = [c for c in cases if c.correlation == CORRELATION_MARKER]
    if marker_cases and detections and not any(d.marker for d in detections):
        warnings.append(
            "경보가 있는데 어느 것도 케이스 marker 를 싣고 있지 않다. "
            "Suricata eve-log 의 http custom 헤더 설정과 레드팀 하니스의 "
            "X-FSL-Case 주입을 확인하라."
        )

    missing_ip = [
        c.case_id
        for c in cases
        if c.correlation == CORRELATION_WINDOW and c.source_ip is None
    ]
    if missing_ip:
        warnings.append(
            "시간창 대응 케이스에 source_ip 가 없어 영원히 미탐으로 집계된다: "
            + ", ".join(missing_ip)
        )

    return tuple(warnings)
