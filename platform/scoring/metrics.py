"""대응 결과를 오탐·미탐 지표로 접는다. 순수 함수만 있다."""

from __future__ import annotations

from scoring.types import CorrelationResult, Score


def score(result: CorrelationResult) -> Score:
    """케이스 단위로 TP/FP/FN/TN 을 세고 지표를 계산한다.

    케이스 하나가 요청을 여러 개 보냈어도 판정은 하나다. 경보의 severity 나
    룰 종류는 보지 않는다 — "경보가 났는가" 만 본다.
    """
    tp = sum(1 for m in result.matches if m.malicious and m.detected)
    fn = sum(1 for m in result.matches if m.malicious and not m.detected)
    fp = sum(1 for m in result.matches if not m.malicious and m.detected)
    tn = sum(1 for m in result.matches if not m.malicious and not m.detected)

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)
    false_positive_rate = _ratio(fp, fp + tn)

    warnings = list(result.warnings)
    if fp + tn == 0:
        warnings.append(
            "benign 케이스가 0건이다. 정상 트래픽이 없으면 전부 차단하는 룰이 "
            "만점을 받는다. 오탐 채점이 이 플랫폼의 존재 이유이므로 "
            "케이스 파일에 정상 트래픽을 추가하라."
        )

    return Score(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=false_positive_rate,
        warnings=tuple(warnings),
    )


def _ratio(numerator: float, denominator: float) -> float:
    """분모가 0이면 0.0. 정의되지 않은 지표를 예외로 터뜨리지 않는다."""
    if denominator == 0:
        return 0.0
    return numerator / denominator
