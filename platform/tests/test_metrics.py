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

@pytest.mark.parametrize("matches, counts, rates", [
    ((("tp", True, True), ("fn", True, False), ("fp", False, True), ("tn", False, False)),
     (1, 1, 1, 1), (0.5, 0.5, 0.5, 0.5)),
    ((("a", True, True), ("b", False, False)), (1, 0, 0, 1), (1.0, 1.0, 1.0, 0.0)),
    ((("a", True, True), ("b", False, True)), (1, 0, 1, 0), (0.5, 1.0, 2 / 3, 1.0)),
    ((("a", True, False),), (0, 1, 0, 0), (0.0, 0.0, 0.0, 0.0)),
])
def test_the_confusion_matrix_and_its_rates_with_block_everything_punished_and_no_division_by_zero(matches, counts, rates):
    s = score(result(*(match(case_id, malicious=malicious, detected=detected)
                       for case_id, malicious, detected in matches)))

    assert (s.tp, s.fn, s.fp, s.tn) == counts
    assert (s.precision, s.recall, s.f1, s.false_positive_rate) == pytest.approx(rates)

@pytest.mark.parametrize("matches, warned", [
    ((("a", True, True),), True),
    ((("a", True, False),), True),
    ((("a", True, True), ("b", False, False)), False),
    ((), False),
])
def test_attacks_with_no_benign_case_beside_them_are_warned_about(matches, warned):
    s = score(result(*(match(case_id, malicious=malicious, detected=detected)
                       for case_id, malicious, detected in matches)))

    assert (("score.warning.no_benign",) in s.warnings) is warned, (
        "without benign cases a block-everything defence scores perfectly; a session "
        "in which nothing has been fired yet has no attack beside which benign traffic is missing"
    )


def test_every_dependency_is_imported_by_something():
    import pathlib, re

    root = pathlib.Path(__file__).resolve().parent.parent.parent
    listed = [
        re.split(r"[><=\[]", line, maxsplit=1)[0].strip().lower()
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

    run = (root / "platform/Dockerfile").read_text() + (root / "platform/entrypoint.sh").read_text()
    for name in RUN_NOT_IMPORTED - {"pytest", "pytest-django"}:
        assert name in run or name == "django", (
            f"{name} is exempt from the import check because something runs it, "
            f"but nothing in the Dockerfile or entrypoint does"
        )
