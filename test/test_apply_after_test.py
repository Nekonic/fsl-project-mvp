import pytest

import plays

CONTROL = "board-sqli-search"
CANDIDATE = (
    'alert http any any -> any any (msg:"tested SQL injection in search"; '
    'flow:established,to_server; http.uri; content:"or 1=1"; nocase; sid:9009982; rev:1;)\n'
)
SETUP = plays.Setup(wargame="board", title="Acceptance apply after test board", probe_cases=(CONTROL,))


@pytest.fixture(scope="module")
def applied_round():
    with plays.Round("board", SETUP) as played:
        text = plays.declared_rules() + CANDIDATE
        ids_test = plays.rule_test_ids(played, text)
        ids_applied = plays.apply_ids(played, text, tested=ids_test.body.get("test") if ids_test.ok else None)
        waf_test = plays.rule_test_waf(played, plays.DETECT_WITHOUT_BLOCKING_SEARCH)
        changed = {**plays.DETECT_WITHOUT_BLOCKING_SEARCH, "paranoia": 2}
        waf_applied = plays.tune_waf(played, changed, tested=waf_test.body.get("test") if waf_test.ok else None)
        fired = plays.fired(played, CONTROL)
        listed = plays.alerts_until(played, lambda listed: any(
            alert["signature"].startswith("tested ") for alert in plays.marked(listed, fired["marker"])))
        yield {"ids_test": ids_test, "ids_applied": ids_applied, "waf_test": waf_test, "waf_applied": waf_applied,
               "ids_versions": plays.ids_versions(played), "waf_versions": plays.waf_versions(played),
               "marker": fired["marker"], "alerts": listed}


def test_the_tested_ids_rules_apply_and_are_recorded_as_the_ones_tested(applied_round):
    assert applied_round["ids_test"].ok, applied_round["ids_test"].text
    assert applied_round["ids_applied"].ok, applied_round["ids_applied"].text
    assert applied_round["ids_applied"].body["same_as_tested"] is True
    assert all(sensor["ok"] for sensor in applied_round["ids_applied"].body["sensors"])
    head = max(applied_round["ids_versions"], key=lambda line: line["version"])
    assert head["tested"] == applied_round["ids_test"].body["test"] and head["same_as_tested"] is True


def test_a_waf_posture_other_than_the_tested_one_applies_and_says_so(applied_round):
    assert applied_round["waf_test"].ok, applied_round["waf_test"].text
    assert applied_round["waf_applied"].ok, applied_round["waf_applied"].text
    assert applied_round["waf_applied"].body["same_as_tested"] is False
    head = max(applied_round["waf_versions"], key=lambda line: line["version"])
    assert head["tested"] == applied_round["waf_test"].body["test"] and head["same_as_tested"] is False


def test_the_applied_rule_runs_on_the_live_sensor(applied_round):
    own = {alert["signature"] for alert in plays.marked(applied_round["alerts"], applied_round["marker"])}

    assert any(signature.startswith("tested ") for signature in own), (
        f"the rule applied after its test never fired on {CONTROL}; its alerts were {sorted(own)}")
