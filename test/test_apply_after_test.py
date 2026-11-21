import pytest

import plays

CONTROL = "board-sqli-search"
CANDIDATE = (
    'alert http any any -> any any (msg:"tested SQL injection in search"; '
    'flow:established,to_server; http.uri; content:"or 1=1"; nocase; sid:9009982; rev:1;)\n'
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
    text = plays.declared_rules() + CANDIDATE
    ids_test = plays.rule_test_ids(played, text)
    ids_applied = plays.apply_ids(played, text, tested=ids_test.body.get("test") if ids_test.ok else None)
    fired = plays.fired(played, CONTROL)
    listed = plays.alerts_until(played, lambda listed: any(
        alert["signature"].startswith("tested ") for alert in plays.marked(listed, fired["marker"])))
    return {"ids_test": ids_test, "ids_applied": ids_applied, "ids_versions": plays.ids_versions(played),
            "marker": fired["marker"], "alerts": listed}


@pytest.fixture(scope="module")
def waf_round(played):
    waf_test = plays.rule_test_waf(played, plays.appended(played, plays.CRS_SETUP, blocking_at(2)))
    changed = plays.appended(played, plays.CRS_SETUP, blocking_at(3))
    waf_applied = plays.tune_waf(played, changed, tested=waf_test.body.get("test") if waf_test.ok else None)
    live = plays.done("defence_waf", played.defence, round_id=played.round)
    broken = plays.tune_waf(played, plays.appended(played, plays.SITE_CONF, NOT_NGINX))
    return {"waf_test": waf_test, "waf_applied": waf_applied, "changed": changed, "live": live,
            "broken": broken, "after_broken": plays.waf_files(played), "waf_versions": plays.waf_versions(played)}


def test_the_tested_ids_rules_apply_and_are_recorded_as_the_ones_tested(applied_round):
    assert applied_round["ids_test"].ok, applied_round["ids_test"].text
    assert applied_round["ids_applied"].ok, applied_round["ids_applied"].text
    assert applied_round["ids_applied"].body["same_as_tested"] is True
    assert all(sensor["ok"] for sensor in applied_round["ids_applied"].body["sensors"])
    head = max(applied_round["ids_versions"], key=lambda line: line["version"])
    assert head["tested"] == applied_round["ids_test"].body["test"] and head["same_as_tested"] is True


def test_waf_files_other_than_the_tested_ones_apply_and_say_so(waf_round):
    assert waf_round["waf_test"].ok, waf_round["waf_test"].text
    assert waf_round["waf_applied"].ok, waf_round["waf_applied"].text
    assert waf_round["waf_applied"].body["same_as_tested"] is False
    live = {one["path"]: one["text"] for one in waf_round["live"]["files"]}
    assert live[plays.CRS_SETUP] == waf_round["changed"][plays.CRS_SETUP] and waf_round["live"]["recorded"], (
        "the applied crs-setup.conf is not the one nginx is running after the reload")
    head = next(line for line in waf_round["waf_versions"] if line["version"] == waf_round["waf_applied"].body["version"])
    assert head["tested"] == waf_round["waf_test"].body["test"] and head["same_as_tested"] is False
    assert head["source"] == "console" and head["sha"] == waf_round["live"]["sha"]


def test_waf_files_nginx_refuses_are_rolled_back(waf_round):
    broken = waf_round["broken"]

    assert broken.status == 422 and "crs_refused" in broken.codes, broken.text
    assert NOT_NGINX not in waf_round["after_broken"][plays.SITE_CONF], "nginx refused the file and it stayed live"
    assert waf_round["after_broken"][plays.CRS_SETUP] == waf_round["changed"][plays.CRS_SETUP]
    assert max(line["version"] for line in waf_round["waf_versions"]) == waf_round["waf_applied"].body["version"], (
        "a refused WAF apply was recorded as a version")


def test_the_applied_rule_runs_on_the_live_sensor(applied_round):
    own = {alert["signature"] for alert in plays.marked(applied_round["alerts"], applied_round["marker"])}

    assert any(signature.startswith("tested ") for signature in own), (
        f"the rule applied after its test never fired on {CONTROL}; its alerts were {sorted(own)}")
