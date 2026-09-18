import pytest

from scoring.metrics import score
from scoring.types import CaseMatch, CorrelationResult


def result(*matches, warnings=()):
    return CorrelationResult(
        matches=tuple(matches), unmatched_detection_ids=(), warnings=tuple(warnings)
    )


def match(case_id, malicious, detected):
    return CaseMatch(
        case_id=case_id,
        name=case_id,
        malicious=malicious,
        detection_ids=("d",) if detected else (),
        detected=detected,
    )


def test_confusion_matrix_counts():
    s = score(
        result(
            match("tp", malicious=True, detected=True),
            match("fn", malicious=True, detected=False),
            match("fp", malicious=False, detected=True),
            match("tn", malicious=False, detected=False),
        )
    )

    assert (s.tp, s.fn, s.fp, s.tn) == (1, 1, 1, 1)


def test_metrics_on_balanced_case():
    s = score(
        result(
            match("tp", malicious=True, detected=True),
            match("fn", malicious=True, detected=False),
            match("fp", malicious=False, detected=True),
            match("tn", malicious=False, detected=False),
        )
    )

    assert s.precision == pytest.approx(0.5)
    assert s.recall == pytest.approx(0.5)
    assert s.f1 == pytest.approx(0.5)
    assert s.false_positive_rate == pytest.approx(0.5)


def test_perfect_defense():
    s = score(
        result(
            match("a", malicious=True, detected=True),
            match("b", malicious=False, detected=False),
        )
    )

    assert (s.precision, s.recall, s.f1, s.false_positive_rate) == (1.0, 1.0, 1.0, 0.0)


def test_block_everything_is_punished_by_false_positive_rate():
    # 전부 차단하는 룰. recall 은 만점이지만 오탐률도 만점이다.
    s = score(
        result(
            match("a", malicious=True, detected=True),
            match("b", malicious=False, detected=True),
        )
    )

    assert s.recall == pytest.approx(1.0)
    assert s.false_positive_rate == pytest.approx(1.0)
    assert s.precision == pytest.approx(0.5)


def test_zero_denominators_yield_zero_not_error():
    s = score(result(match("a", malicious=True, detected=False)))

    assert s.precision == 0.0
    assert s.f1 == 0.0
    assert s.false_positive_rate == 0.0


def test_warns_when_there_are_no_benign_cases():
    s = score(result(match("a", malicious=True, detected=True)))

    assert any("benign" in w for w in s.warnings)


def test_no_benign_warning_when_benign_cases_exist():
    s = score(
        result(
            match("a", malicious=True, detected=True),
            match("b", malicious=False, detected=False),
        )
    )

    assert not any("benign" in w for w in s.warnings)


def test_correlation_warnings_are_carried_through():
    s = score(result(match("a", malicious=True, detected=True), warnings=("보존됨",)))

    assert "보존됨" in s.warnings


def test_empty_result_is_all_zero_with_warning():
    s = score(result())

    assert (s.tp, s.fp, s.fn, s.tn) == (0, 0, 0, 0)
    assert any("benign" in w for w in s.warnings)
