import pytest

import plays

CONTROL = "board-sqli-search"
CANDIDATE = (
    'alert http any any -> any any (msg:"tested SQL injection in search"; '
    'flow:established,to_server; http.uri; content:"1=1"; sid:9009982; rev:1;)\n'
)
NOT_NGINX = "not_a_directive on;\n"
SETUP = plays.Setup(wargame="board", title="Acceptance apply after test board", probe_cases=(CONTROL,))


def blocking_at(level: int) -> str:
    return f'SecAction "id:900000,phase:1,pass,t:none,nolog,setvar:tx.blocking_paranoia_level={level}"\n'


@pytest.fixture(scope="module")
def played():
    with plays.Round("board", SETUP) as held:
        yield held


@pytest.fixture(scope="module")
def applied_round(played):
    text = plays.declared_rules(played.wargame) + CANDIDATE
    ids_test = plays.rule_test_ids(played, text)
    ids_applied = plays.apply_ids(played, text)
    fired = plays.fired(played, CONTROL)
    listed = plays.alerts_until(played, lambda listed: any(
        alert["signature"].startswith("tested ") for alert in plays.marked(listed, fired["marker"])))
    return {"ids_test": ids_test, "ids_applied": ids_applied, "ids_versions": plays.ids_versions(played),
            "marker": fired["marker"], "alerts": listed}


@pytest.fixture(scope="module")
def waf_round(played):
    tested_files = plays.appended(played, plays.CRS_SETUP, blocking_at(2))
    waf_test = plays.rule_test_waf(played, tested_files)
    other = plays.tune_waf(played, plays.appended(played, plays.CRS_SETUP, blocking_at(3)),
                           tested=waf_test.body.get("test") if waf_test.ok else None)
    waf_applied = plays.tune_waf(played, tested_files, tested=waf_test.body.get("test") if waf_test.ok else None)
    live = plays.done("defence_waf", played.defence, round_id=played.round)
    broken_files = plays.appended(played, plays.SITE_CONF, NOT_NGINX)
    broken_test = plays.rule_test_waf(played, broken_files)
    broken = plays.tune_waf(played, broken_files, tested=broken_test.body.get("test") if broken_test.ok else None)
    return {"waf_test": waf_test, "other": other, "waf_applied": waf_applied, "changed": tested_files, "live": live,
            "broken_test": broken_test, "broken": broken, "after_broken": plays.waf_files(played),
            "waf_versions": plays.waf_versions(played)}


def test_tested_ids_rules_reloaded_in_the_ids_terminal_are_recorded_as_a_terminal_version(applied_round):
    assert applied_round["ids_test"].ok, applied_round["ids_test"].text
    assert applied_round["ids_applied"].ok, applied_round["ids_applied"].text
    head = max(applied_round["ids_versions"], key=lambda line: line["version"])
    assert head == applied_round["ids_applied"].version and head["source"] == "terminal"
    assert head["tested"] is not None and head["tested"] >= applied_round["ids_test"].body["test"], head
    assert head["same_as_tested"] is True, "a terminal reload is tied to the passed test of the same text"


def test_only_the_waf_files_a_test_passed_apply(waf_round):
    assert waf_round["waf_test"].ok and waf_round["waf_test"].body["passed"], waf_round["waf_test"].text
    assert waf_round["other"].status == 409 and "not_tested" in waf_round["other"].codes, waf_round["other"].text
    assert waf_round["waf_applied"].ok, waf_round["waf_applied"].text
    assert waf_round["waf_applied"].body["same_as_tested"] is True
    live = {one["path"]: one["text"] for one in waf_round["live"]["files"]}
    assert live[plays.CRS_SETUP] == waf_round["changed"][plays.CRS_SETUP] and waf_round["live"]["recorded"], (
        "the applied crs-setup.conf is not the one nginx is running after the reload")
    head = next(line for line in waf_round["waf_versions"] if line["version"] == waf_round["waf_applied"].body["version"])
    assert head["tested"] == waf_round["waf_test"].body["test"] and head["same_as_tested"] is True
    assert head["source"] == "console" and head["sha"] == waf_round["live"]["sha"]


def test_waf_files_nginx_refuses_fail_the_test_and_cannot_be_applied(waf_round):
    assert waf_round["broken_test"].ok and waf_round["broken_test"].body["ok"] is False, waf_round["broken_test"].text
    assert waf_round["broken"].status == 409 and "not_tested" in waf_round["broken"].codes, waf_round["broken"].text
    assert NOT_NGINX not in waf_round["after_broken"][plays.SITE_CONF], "nginx refused the file and it stayed live"
    assert waf_round["after_broken"][plays.CRS_SETUP] == waf_round["changed"][plays.CRS_SETUP]
    assert max(line["version"] for line in waf_round["waf_versions"]) == waf_round["waf_applied"].body["version"], (
        "a refused WAF apply was recorded as a version")


def test_the_applied_rule_runs_on_the_live_sensor(applied_round):
    own = {alert["signature"] for alert in plays.marked(applied_round["alerts"], applied_round["marker"])}

    assert any(signature.startswith("tested ") for signature in own), (
        f"the rule applied after its test never fired on {CONTROL}; its alerts were {sorted(own)}")
