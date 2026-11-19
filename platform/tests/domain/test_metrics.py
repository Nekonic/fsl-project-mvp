from datetime import datetime, timedelta, timezone

import pytest

from domain.scoring.correlate import correlate
from domain.scoring.metrics import free_actions, per_case, score, verdict
from domain.types import CaseMatch, CaseRecord, CorrelationResult, DetectionRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def result(*matches, warnings=()):
    return CorrelationResult(matches=tuple(matches), unmatched_detection_ids=(), warnings=tuple(warnings))


def match(case_id, malicious, detected):
    return CaseMatch(case_id=case_id, name=case_id, malicious=malicious,
                     detection_ids=("d",) if detected else (), detected=detected)


def case(case_id, malicious, correlation="marker", source_ip=None, expect=None, marker=None):
    return CaseRecord(case_id=case_id, name=case_id, malicious=malicious, correlation=correlation,
                      marker=marker or case_id, source_ip=source_ip, started_at=T0,
                      ended_at=T0 + timedelta(seconds=5), expect=expect)


def det(detection_id, marker=None, src_ip=None, signature="", blocked=False):
    return DetectionRecord(detection_id=detection_id, timestamp=T0 + timedelta(seconds=1), src_ip=src_ip,
                           marker=marker, signature=signature, blocked=blocked)


@pytest.mark.parametrize("matches, counts, rates", [
    ((("tp", True, True), ("fn", True, False), ("fp", False, True), ("tn", False, False)),
     (1, 1, 1, 1), (0.5, 0.5, 0.5, 0.5)),
    ((("a", True, True), ("b", False, False)), (1, 0, 0, 1), (1.0, 1.0, 1.0, 0.0)),
    ((("a", True, True), ("b", False, True)), (1, 0, 1, 0), (0.5, 1.0, 2 / 3, 1.0)),
    ((("a", True, False),), (0, 1, 0, 0), (0.0, 0.0, 0.0, 0.0)),
])
def test_the_confusion_matrix_and_its_rates_without_division_by_zero(matches, counts, rates):
    s = score(result(*(match(c, m, d) for c, m, d in matches)))

    assert (s.tp, s.fn, s.fp, s.tn) == counts
    assert (s.precision, s.recall, s.f1, s.false_positive_rate) == pytest.approx(rates)


@pytest.mark.parametrize("matches, warned", [
    ((("a", True, True),), True),
    ((("a", True, True), ("b", False, False)), False),
    ((), False),
])
def test_attacks_with_no_benign_case_beside_them_are_warned_about(matches, warned):
    s = score(result(*(match(c, m, d) for c, m, d in matches)))

    assert (("no_benign",) in s.warnings) is warned


def test_one_declared_case_is_one_decision_however_many_alerts_it_drew():
    cases = [case("sqlmap", True)]
    alerts = [det(f"d{n}", marker="sqlmap") for n in range(2000)]

    s = score(correlate(cases, alerts))

    assert (s.tp, s.fn, s.fp, s.tn) == (1, 0, 0, 0)


def test_free_actions_leave_the_totals_unchanged():
    declared = [case("sqli", True), case("browse", False)]
    alerts = [det("d1", marker="sqli")]
    free = [case(f"free{n}", None, correlation="window", source_ip="10.0.0.5") for n in range(50)]
    noisy = alerts + [det(f"f{n}", src_ip="10.0.0.5") for n in range(50)]

    before = score(correlate(declared, alerts))
    after = score(correlate(declared + free, noisy))

    assert (after.tp, after.fn, after.fp, after.tn) == (before.tp, before.fn, before.fp, before.tn) == (1, 0, 0, 1)


def test_per_case_holds_only_declared_cases_with_verdicts_and_corroboration():
    cases = [case("sqli", True, expect="SQL"), case("browse", False), case("free", None, "window", "10.0.0.5")]
    alerts = [det("d1", marker="sqli", signature="SQL Injection Attack"), det("d2", src_ip="10.0.0.5")]

    rows = per_case(correlate(cases, alerts), cases, alerts)

    assert [(r.case_id, r.verdict, r.corroborated, r.alerts) for r in rows] == [
        ("sqli", "tp", True, 1), ("browse", "tn", None, 0)]


def test_a_signature_that_also_fires_on_benign_traffic_corroborates_nothing():
    catch_all = "SQL XSS traversal"
    cases = [case("sqli", True, expect="SQL"), case("browse", False)]
    alerts = [det("d1", marker="sqli", signature=catch_all), det("d2", marker="browse", signature=catch_all)]

    rows = per_case(correlate(cases, alerts), cases, alerts)

    assert rows[0].corroborated is False
    assert rows[1].verdict == "fp"


def test_free_actions_are_reported_by_origin():
    cases = [case("a1", None, "window", "10.0.0.5"), case("a2", None, "window", "10.0.0.5"),
             case("a3", None, "window", "10.0.0.6"), case("sqli", True)]
    alerts = [det("d1", src_ip="10.0.0.5", blocked=True), det("d2", src_ip="10.0.0.5"), det("d3", marker="sqli")]

    rows = free_actions(correlate(cases, alerts), cases, alerts)

    assert [(r.ip, r.actions, r.alerts, r.refused) for r in rows] == [("10.0.0.5", 2, 2, 1), ("10.0.0.6", 1, 0, 0)]


def test_verdict_codes():
    assert [verdict(True, True), verdict(True, False), verdict(False, True), verdict(False, False)] == [
        "tp", "fn", "fp", "tn"]
