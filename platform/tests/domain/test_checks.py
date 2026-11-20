from datetime import datetime, timedelta, timezone

import pytest

from domain.checks import (
    CHECK_SCHEMAS,
    DETAIL_CODES,
    FACTS_NEEDED,
    JUDGES,
    AppliedRuleSet,
    Facts,
    check_params,
    judge,
    waf_changes,
)
from domain.types import ActionRecord, CommandRecord, DetectionRecord, ObjectiveRecord
from domain.verdicts import Probe, table

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
OPENED = Facts(step_opened_at=T0)


def later(seconds):
    return T0 + timedelta(seconds=seconds)


def test_schemas_judges_and_facts_name_the_same_kinds():
    assert set(CHECK_SCHEMAS) == set(JUDGES) == set(FACTS_NEEDED)
    assert set(FACTS_NEEDED["sent"]) <= set(Facts.__dataclass_fields__)
    assert all(set(needed) <= set(Facts.__dataclass_fields__) for needed in FACTS_NEEDED.values())


@pytest.mark.parametrize("given, mode, passed, code", [
    ("  Union Select ", "text", True, None),
    ("union", "text", False, "wrong_answer"),
    ("1,234", "number", True, None),
    ("1,234 ea", "number", True, None),
    ("1,234", "text", False, "wrong_answer"),
    ("recon > exploit > loot", "order", True, None),
    ("exploit, recon, loot", "order", False, "wrong_order"),
    ("", "text", False, "no_answer"),
])
def test_answer_normalises_as_the_check_says(given, mode, passed, code):
    accept = ["recon", "exploit", "loot"] if mode == "order" else ["1234"] if mode == "number" else ["UNION SELECT"]

    verdict = judge("answer", {"accept": accept, "normalise": mode}, given, Facts())

    assert (verdict.passed, verdict.detail_code) == (passed, code)
    assert verdict.outcome == ("passed" if passed else "not_yet")


def test_choice_passes_only_on_the_correct_option():
    spec = {"options": ["a", "b"], "correct": "b"}

    assert judge("choice", spec, "b", Facts()).passed
    assert judge("choice", spec, "a", Facts()).detail_code == "wrong_choice"


def test_loot_passes_only_when_the_referee_reports_the_objective_lost_through_loot():
    spec = {"objective": "db"}
    by_effect = Facts(objectives=(ObjectiveRecord("db", "db", "c", 1, achieved_at=T0, by_loot=False),))
    by_loot = Facts(objectives=(ObjectiveRecord("db", "db", "c", 1, achieved_at=T0, by_loot=True),))

    assert judge("loot", spec, None, Facts(objectives=(ObjectiveRecord("db", "db", "c", 1),))).detail_code == "objective_kept"
    assert not judge("loot", spec, None, by_effect).passed
    assert judge("loot", spec, None, by_loot).passed


def alert(marker, signature):
    return DetectionRecord(marker, T0, None, marker, signature=signature)


PROBES = [Probe("sqli", True, "m-sqli", expect="SQL"), Probe("browse", False, "m-browse")]


@pytest.mark.parametrize("alerts, passed, code", [
    ([alert("m-sqli", "SQL injection")], True, None),
    ([], False, "case_not_detected"),
    ([alert("m-sqli", "generic anomaly")], False, "not_corroborated"),
    ([alert("m-sqli", "SQL injection"), alert("m-browse", "noise")], False, "benign_alerted"),
])
def test_rule_test_reads_the_seat_s_latest_test(alerts, passed, code):
    facts = Facts(latest_tests={"ids": table(PROBES, alerts, "ids")})

    verdict = judge("rule_test", {"engine": "ids", "case": "sqli"}, None, facts)

    assert (verdict.passed, verdict.detail_code) == (passed, code)


def test_rule_test_without_a_test_or_the_case_is_not_yet():
    assert judge("rule_test", {"engine": "waf", "case": "sqli"}, None, Facts()).detail_code == "no_test"
    facts = Facts(latest_tests={"ids": table(PROBES, [], "ids")})
    assert judge("rule_test", {"engine": "ids", "case": "xss"}, None, facts).detail_code == "case_untested"


def test_rule_applied_counts_only_applies_after_the_step_opened_with_the_flag_as_required():
    before = AppliedRuleSet("ids", 1, later(-5), True)
    untested = AppliedRuleSet("ids", 2, later(5), False)
    tested = AppliedRuleSet("ids", 3, later(6), True)

    assert judge("rule_applied", {"engine": "ids", "same_as_tested": False},
                 None, Facts(step_opened_at=T0, applied=(before,))).detail_code == "not_applied"
    assert judge("rule_applied", {"engine": "ids", "same_as_tested": False},
                 None, Facts(step_opened_at=T0, applied=(untested,))).passed
    assert judge("rule_applied", {"engine": "ids", "same_as_tested": True},
                 None, Facts(step_opened_at=T0, applied=(untested,))).detail_code == "not_same_as_tested"
    assert judge("rule_applied", {"engine": "ids", "same_as_tested": True},
                 None, Facts(step_opened_at=T0, applied=(untested, tested))).passed
    assert not judge("rule_applied", {"engine": "waf", "same_as_tested": False},
                     None, Facts(step_opened_at=T0, applied=(tested,))).passed


def test_alert_seen_matches_on_every_given_field():
    facts = Facts(detections=(DetectionRecord("d1", T0, None, "sqli", engine="ids", rule="1000001"),))

    assert judge("alert_seen", {"engine": "ids", "rule": "1000001", "case": "sqli"}, None, facts).passed
    assert judge("alert_seen", {}, None, facts).passed
    assert judge("alert_seen", {"engine": "waf"}, None, facts).detail_code == "no_alert"
    assert not judge("alert_seen", {"case": "xss"}, None, facts).passed


def action(seconds, method, path):
    return ActionRecord("a1", "request", "m1", "marker", "10.0.0.1", later(seconds), later(seconds), method=method, path=path)


def test_sent_matches_an_action_since_the_step_opened():
    facts = Facts(step_opened_at=T0, actions=(action(-1, "GET", "/search?q=1"), action(2, "post", "/login")))

    assert judge("sent", {"method": "POST", "path_has": "/login"}, None, facts).passed
    assert judge("sent", {"path_has": "/search"}, None, facts).detail_code == "not_sent"


def test_kali_matches_a_command_line_since_the_step_opened():
    facts = Facts(step_opened_at=T0, commands=(CommandRecord(later(-1), "nmap target"), CommandRecord(later(1), "curl -I x")))

    assert judge("kali", {"command_has": "curl"}, None, facts).passed
    assert judge("kali", {"command_has": "nmap"}, None, facts).detail_code == "no_command"


def test_waf_changes_name_the_direction_of_each_field():
    before = {"paranoia": 1, "exclusions": [{"rule_id": 942100, "target": "", "path": ""}]}
    after = {"paranoia": 2, "thresholds": {"inbound": 3}, "detection_only": True,
             "exclusions": [{"rule_id": 942100, "target": "ARGS:q", "path": "/search/"}]}

    assert waf_changes(before, after) == {
        "paranoia": ("raised",), "thresholds": ("lowered",), "exclusions": ("added", "removed", "narrowed"),
        "detection_only": ("on",)}
    assert waf_changes(after, after) == {"paranoia": (), "thresholds": (), "exclusions": (), "detection_only": ()}


def test_waf_changed_judges_the_posture_diff():
    facts = Facts(waf_before={"paranoia": 1}, waf_after={"paranoia": 3})

    assert judge("waf_changed", {"field": "paranoia", "change": "raised"}, None, facts).passed
    assert judge("waf_changed", {"field": "paranoia", "change": "lowered"}, None, facts).detail_code == "waf_unchanged"


def test_every_detail_code_a_judge_returns_is_declared():
    facts = Facts()
    specs = {
        "answer": {"accept": ["x"]}, "choice": {"options": ["a"], "correct": "a"}, "loot": {"objective": "o"},
        "rule_test": {"engine": "ids", "case": "c"}, "rule_applied": {"engine": "ids", "same_as_tested": True},
        "alert_seen": {}, "sent": {"path_has": "/"}, "kali": {"command_has": "x"},
        "waf_changed": {"field": "paranoia", "change": "raised"},
    }
    for kind, spec in specs.items():
        assert check_params(kind, spec, "check") == []
        for answer in (None, "wrong"):
            code = judge(kind, spec, answer, facts).detail_code
            assert code is None or code in DETAIL_CODES


@pytest.mark.parametrize("kind, params, path, code", [
    ("click", {}, "check.kind", "unknown_check"),
    (["answer"], {}, "check.kind", "unknown_check"),
    ("answer", [], "check.params", "not_an_object"),
    ("answer", {}, "check.params.accept", "required"),
    ("answer", {"accept": []}, "check.params.accept", "not_a_text_list"),
    ("answer", {"accept": ["x"], "normalise": "fuzzy"}, "check.params.normalise", "not_a_choice"),
    ("answer", {"accept": ["x"], "extra": 1}, "check.params.extra", "unknown_field"),
    ("rule_applied", {"engine": "ids", "same_as_tested": "yes"}, "check.params.same_as_tested", "not_a_boolean"),
    ("choice", {"options": ["a"], "correct": "b"}, "check.params.correct", "not_an_option"),
    ("waf_changed", {"field": "paranoia", "change": "on"}, "check.params.change", "not_a_choice"),
])
def test_check_params_report_errors_by_path(kind, params, path, code):
    errors = check_params(kind, params, "check")

    assert (errors[0].path, errors[0].code) == (path, code)
