from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CORRELATION_MARKER = "marker"
CORRELATION_WINDOW = "window"
CORRELATION_STRATEGIES = (CORRELATION_MARKER, CORRELATION_WINDOW)

ACTION_CASE = "case"
ACTION_KINDS = ("request", "tool", "command", "case", "site")

ENGINE_IDS = "ids"
ENGINE_WAF = "waf"
ENGINES = (ENGINE_IDS, ENGINE_WAF)

TP, FN, FP, TN = "tp", "fn", "fp", "tn"

RESPONSE_ORIGIN = "origin"
RESPONSE_VERSION = "version"


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    name: str
    malicious: bool | None
    correlation: str
    marker: str | None
    source_ip: str | None
    started_at: datetime
    ended_at: datetime
    expect: str | None = None

    @property
    def declared(self) -> bool:
        return self.malicious is not None


@dataclass(frozen=True)
class ActionRecord:
    action_id: str
    kind: str
    marker: str
    correlation: str
    source_ip: str | None
    started_at: datetime
    ended_at: datetime
    case_id: str | None = None
    malicious: bool | None = None
    expect: str | None = None
    method: str | None = None
    path: str | None = None

    def as_case(self) -> CaseRecord:
        return CaseRecord(
            case_id=self.case_id or self.action_id,
            name=self.case_id or self.kind,
            malicious=self.malicious if self.kind == ACTION_CASE else None,
            correlation=self.correlation,
            marker=self.marker,
            source_ip=self.source_ip,
            started_at=self.started_at,
            ended_at=self.ended_at,
            expect=self.expect,
        )


@dataclass(frozen=True)
class DetectionRecord:
    detection_id: str
    timestamp: datetime
    src_ip: str | None
    marker: str | None
    engine: str = ""
    rule: str = ""
    signature: str = ""
    uri: str = ""
    blocked: bool = False


@dataclass(frozen=True)
class ResponseRecord:
    at: datetime
    kind: str
    source_ip: str | None = None
    replayed: frozenset[str] = frozenset()
    refused: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CommandRecord:
    at: datetime
    line: str


@dataclass(frozen=True)
class ObjectiveRecord:
    key: str
    name: str
    category: str
    difficulty: int
    achieved_at: datetime | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    by_loot: bool = False

    @property
    def lost(self) -> bool:
        return self.achieved_at is not None


@dataclass(frozen=True)
class CaseMatch:
    case_id: str
    name: str
    malicious: bool | None
    detection_ids: tuple[str, ...]
    detected: bool

    @property
    def declared(self) -> bool:
        return self.malicious is not None


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


@dataclass(frozen=True)
class FieldError:
    path: str
    code: str
    params: tuple[tuple[str, object], ...] = ()
