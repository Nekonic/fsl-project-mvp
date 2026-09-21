from __future__ import annotations

from scoring.types import CorrelationResult, Score

def score(result: CorrelationResult) -> Score:
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
            "There are no benign cases. Without normal traffic, a rule that "
            "blocks everything scores perfectly. Scoring false positives is "
            "the whole point of this platform, so add normal traffic to the "
            "case file."
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
    if denominator == 0:
        return 0.0
    return numerator / denominator
