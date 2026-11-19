from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.scoring.corroborate import corroborated, indiscriminate_signatures
from domain.types import FN, FP, TN, TP, CaseRecord, CorrelationResult, DetectionRecord, Score

ONE_CASE_ONE_DECISION = "one_case_one_decision"


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    name: str
    malicious: bool
    verdict: str
    detection_ids: tuple[str, ...]
    corroborated: bool | None

    @property
    def alerts(self) -> int:
        return len(self.detection_ids)


@dataclass(frozen=True)
class OriginActivity:
    ip: str
    actions: int
    alerts: int
    refused: int


def verdict(malicious: bool, detected: bool) -> str:
    if malicious:
        return TP if detected else FN
    return FP if detected else TN


def score(result: CorrelationResult) -> Score:
    declared = [m for m in result.matches if m.declared]
    tp = sum(1 for m in declared if m.malicious and m.detected)
    fn = sum(1 for m in declared if m.malicious and not m.detected)
    fp = sum(1 for m in declared if not m.malicious and m.detected)
    tn = sum(1 for m in declared if not m.malicious and not m.detected)

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    warnings = list(result.warnings)
    if tp + fn and not fp + tn:
        warnings.append(("no_benign",))

    return Score(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        false_positive_rate=_ratio(fp, fp + tn),
        warnings=tuple(warnings),
    )


def per_case(
    result: CorrelationResult,
    cases: Sequence[CaseRecord],
    detections: Sequence[DetectionRecord],
) -> tuple[CaseOutcome, ...]:
    expect = {case.case_id: case.expect for case in cases}
    signatures = {d.detection_id: d.signature for d in detections}
    noise = indiscriminate_signatures(result, signatures)
    return tuple(
        CaseOutcome(
            case_id=m.case_id,
            name=m.name,
            malicious=bool(m.malicious),
            verdict=verdict(bool(m.malicious), m.detected),
            detection_ids=m.detection_ids,
            corroborated=corroborated(
                expect.get(m.case_id),
                [signatures[d] for d in m.detection_ids if d in signatures],
                noise,
            ),
        )
        for m in result.matches
        if m.declared
    )


def free_actions(
    result: CorrelationResult,
    cases: Sequence[CaseRecord],
    detections: Sequence[DetectionRecord],
) -> tuple[OriginActivity, ...]:
    source = {case.case_id: case.source_ip or "" for case in cases}
    blocked = {d.detection_id for d in detections if d.blocked}
    actions: dict[str, int] = {}
    alerts: dict[str, set[str]] = {}
    for match in result.matches:
        if match.declared:
            continue
        ip = source.get(match.case_id, "")
        actions[ip] = actions.get(ip, 0) + 1
        alerts.setdefault(ip, set()).update(match.detection_ids)
    return tuple(
        OriginActivity(ip=ip, actions=actions[ip], alerts=len(alerts[ip]), refused=len(alerts[ip] & blocked))
        for ip in sorted(actions)
    )


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
