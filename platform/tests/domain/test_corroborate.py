from domain.scoring.corroborate import corroborated, indiscriminate_signatures
from domain.types import CaseMatch, CorrelationResult

ANOMALY = "Inbound Anomaly Score Exceeded (Total Score: 5)"


def test_a_case_that_declares_nothing_is_not_judged():
    assert corroborated(None, ["SQLi attempt - URI"]) is None
    assert corroborated("", ["SQLi attempt - URI"]) is None


def test_evidence_matching_the_mechanism_corroborates_case_insensitively():
    assert corroborated("SQL", ["SQLi attempt - request body"]) is True
    assert corroborated("TRAVERSAL", ["path traversal attempt"]) is True


def test_an_alert_about_something_else_does_not_corroborate():
    assert corroborated("traversal", ["XSS attempt - script tag"]) is False
    assert corroborated("SQL", [ANOMALY]) is False
    assert corroborated("SQL", [ANOMALY, "SQL Injection Attack Detected"]) is True


def test_an_indiscriminate_signature_corroborates_nothing_but_hides_no_real_alert():
    catch_all = "SQL XSS traversal Restricted File"

    assert corroborated("SQL", [catch_all], indiscriminate={catch_all}) is False
    assert corroborated("SQL", [catch_all, "SQLi attempt - URI"], indiscriminate={catch_all}) is True


def test_indiscriminate_signatures_are_those_that_fired_on_benign_cases():
    result = CorrelationResult(
        matches=(
            CaseMatch("browse", "browse", False, ("d1",), True),
            CaseMatch("sqli", "sqli", True, ("d2",), True),
            CaseMatch("free", "free", None, ("d3",), True),
        ),
        unmatched_detection_ids=(),
        warnings=(),
    )

    noise = indiscriminate_signatures(result, {"d1": "catch-all", "d2": "SQLi", "d3": "free noise"})

    assert noise == {"catch-all"}
