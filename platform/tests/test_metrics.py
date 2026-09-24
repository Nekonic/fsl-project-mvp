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

    assert ("score.warning.no_benign",) in s.warnings

def test_no_benign_warning_when_benign_cases_exist():
    s = score(
        result(
            match("a", malicious=True, detected=True),
            match("b", malicious=False, detected=False),
        )
    )

    assert ("score.warning.no_benign",) not in s.warnings

def test_correlation_warnings_are_carried_through():
    s = score(result(match("a", malicious=True, detected=True), warnings=(("carried through",),)))

    assert ("carried through",) in s.warnings

def test_empty_result_is_all_zero_with_warning():
    s = score(result())

    assert (s.tp, s.fp, s.fn, s.tn) == (0, 0, 0, 0)
    assert ("score.warning.no_benign",) in s.warnings


def test_every_dependency_is_imported_by_something():
    import pathlib, re

    root = pathlib.Path(__file__).resolve().parent.parent.parent
    listed = [
        re.split(r"[><=\[]", line, 1)[0].strip().lower()
        for line in (root / "platform/requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    sources = "\n".join(
        p.read_text()
        for d in ("platform", "redteam", "test", "bin")
        for p in (root / d).rglob("*.py")
    )

    MODULE = {"pyyaml": "yaml", "pytest-django": "pytest_django"}
    RUN_NOT_IMPORTED = {"django", "pytest", "pytest-django", "waitress"}

    unused = [
        name for name in listed
        if name not in RUN_NOT_IMPORTED
        and not re.search(
            rf"^\s*(import|from)\s+{re.escape(MODULE.get(name, name))}\b", sources, re.M
        )
    ]

    assert not unused, (
        f"declared and never imported, so every build pulls them for nothing: {unused}"
    )

    run = root / "platform/Dockerfile"
    for name in RUN_NOT_IMPORTED - {"pytest", "pytest-django"}:
        assert name in run.read_text() or name == "django", (
            f"{name} is exempt from the import check because something runs it, "
            f"but nothing in the Dockerfile does"
        )
