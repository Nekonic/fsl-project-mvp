from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.scoring.correlate import correlate
from domain.scoring.metrics import per_case
from domain.types import (
    CORRELATION_MARKER,
    ENGINE_IDS,
    ENGINE_WAF,
    FN,
    FP,
    TN,
    TP,
    CaseRecord,
    DetectionRecord,
)

NOT_RECORDED = "not_recorded"
TOOL_CASE = "tool_case"
RECORDING_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Probe:
    case: str
    malicious: bool
    marker: str
    expect: str | None = None
    recorded: bool = True
    tool_case: bool = False


@dataclass(frozen=True)
class CaseVerdict:
    case: str
    malicious: bool
    verdict: str
    corroborated: bool | None
    alerts: tuple[tuple[str, str], ...]
    recorded_run: bool


@dataclass(frozen=True)
class Untested:
    case: str
    reason: str


@dataclass(frozen=True)
class Change:
    case: str
    was: str
    now: str


@dataclass(frozen=True)
class VerdictTable:
    cases: tuple[CaseVerdict, ...]
    totals: tuple[tuple[str, int], ...]
    untested: tuple[Untested, ...]
    against_applied: tuple[Change, ...]

    def verdict_of(self, case: str) -> CaseVerdict | None:
        return next((row for row in self.cases if row.case == case), None)

    def total(self, verdict: str) -> int:
        return dict(self.totals)[verdict]


def untested_reason(probe: Probe, engine: str) -> str | None:
    if not probe.recorded:
        return NOT_RECORDED
    if probe.tool_case and engine == ENGINE_WAF:
        return TOOL_CASE
    return None


def table(
    probes: Sequence[Probe],
    alerts: Sequence[DetectionRecord],
    engine: str,
    applied: VerdictTable | None = None,
) -> VerdictTable:
    if engine not in (ENGINE_IDS, ENGINE_WAF):
        raise ValueError(f"unknown engine {engine!r}")
    untested = tuple(
        Untested(probe.case, reason) for probe in probes if (reason := untested_reason(probe, engine))
    )
    skipped = {row.case for row in untested}
    tested = [probe for probe in probes if probe.case not in skipped]
    cases = [
        CaseRecord(
            case_id=probe.case,
            name=probe.case,
            malicious=probe.malicious,
            correlation=CORRELATION_MARKER,
            marker=probe.marker,
            source_ip=None,
            started_at=RECORDING_TIME,
            ended_at=RECORDING_TIME,
            expect=probe.expect,
        )
        for probe in tested
    ]
    result = correlate(cases, alerts)
    by_id = {alert.detection_id: alert for alert in alerts}
    tool = {probe.case for probe in tested if probe.tool_case}
    rows = tuple(
        CaseVerdict(
            case=outcome.case_id,
            malicious=outcome.malicious,
            verdict=outcome.verdict,
            corroborated=outcome.corroborated,
            alerts=tuple((by_id[d].rule, by_id[d].signature) for d in outcome.detection_ids),
            recorded_run=outcome.case_id in tool,
        )
        for outcome in per_case(result, cases, alerts)
    )
    return VerdictTable(
        cases=rows,
        totals=tuple((v, sum(1 for row in rows if row.verdict == v)) for v in (TP, FN, FP, TN)),
        untested=untested,
        against_applied=_changes(rows, applied),
    )


def _changes(rows: Sequence[CaseVerdict], applied: VerdictTable | None) -> tuple[Change, ...]:
    if applied is None:
        return ()
    before = {row.case: row.verdict for row in applied.cases}
    return tuple(
        Change(row.case, before[row.case], row.verdict)
        for row in rows
        if row.case in before and before[row.case] != row.verdict
    )
