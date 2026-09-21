from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MARKER_HEADER = "X-FSL-Case"

CORRELATION_MARKER = "marker"
CORRELATION_WINDOW = "window"
CORRELATION_STRATEGIES = (CORRELATION_MARKER, CORRELATION_WINDOW)

@dataclass(frozen=True)
class CaseRecord:

    case_id: str
    name: str
    malicious: bool
    correlation: str
    source_ip: str | None
    started_at: datetime
    ended_at: datetime

@dataclass(frozen=True)
class DetectionRecord:

    detection_id: str
    source: str
    signature: str
    timestamp: datetime
    src_ip: str | None
    marker: str | None

@dataclass(frozen=True)
class CaseMatch:
    case_id: str
    name: str
    malicious: bool
    detection_ids: tuple[str, ...]
    detected: bool

@dataclass(frozen=True)
class CorrelationResult:
    matches: tuple[CaseMatch, ...]
    unmatched_detection_ids: tuple[str, ...]
    warnings: tuple[tuple[str, ...], ...]

@dataclass(frozen=True)
class Score:
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    warnings: tuple[tuple[str, ...], ...]
