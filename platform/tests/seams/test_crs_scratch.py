import json

import pytest

from cr.config import WafConfig
from rules import crs
from testing.fakes import FakeRunner

WAF = WafConfig(rules="/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf",
                reload="nginx -t 2>&1 && nginx -s reload 2>&1", pid="/run/nginx.pid")
POSTURE = {"paranoia": 2, "exclusions": [{"rule_id": 942100, "target": "ARGS:q", "path": "/search/"}]}
PROBES = [
    {"marker": "board-sqli-union", "method": "GET", "path": "/search/?q=1%27+UNION+SELECT", "host": "board.com"},
    {"marker": "board-normal-comment", "method": "POST", "path": "/posts/1/comment/", "host": "board.com",
     "headers": {"Content-Type": "application/x-www-form-urlencoded", "Host": "evil"}, "body": "body=hi"},
]
AUDIT = "\n".join(json.dumps(record) for record in [
    {"transaction": {"request": {"headers": {"X-Request-ID": "board-sqli-union"}},
                     "messages": [{"message": "SQL Injection Attack Detected via libinjection",
                                   "details": {"ruleId": "942100"}},
                                  {"message": "Inbound Anomaly Score Exceeded", "details": {"ruleId": "949110"}}]}},
    {"transaction": {"request": {"headers": {"x-request-id": "noise"}}, "messages": []}},
]) + "\nnot json\n"


def gateway():
    return (FakeRunner()
            .answer("nginx -t -p", "nginx: configuration file test is successful")
            .answer("board-sqli-union", "403")
            .answer("board-normal-comment", "200")
            .answer("audit.log", AUDIT))


def test_the_scratch_lives_apart_from_the_live_crs_tree_and_its_port_is_named_by_the_test():
    scratch = crs.scratch_for(WAF, 7)

    assert scratch.prefix == "/var/lib/cr-crstest/test-7"
    assert (scratch.port, scratch.upstream_port) == (18007, 19007)
    assert WAF.tree == "/etc/nginx/modsecurity"


@pytest.mark.parametrize("scratch", ["/etc/nginx/modsecurity", "/etc/nginx/modsecurity/crs/rules"])
def test_a_scratch_on_or_around_the_live_tree_is_refused(scratch):
    with pytest.raises(ValueError):
        crs.scratch_for(WafConfig(rules=WAF.rules, scratch=scratch), 7)


def test_a_test_id_must_be_a_positive_number():
    with pytest.raises(ValueError):
        crs.scratch_for(WAF, 0)


def test_the_scratch_check_runs_nginx_t_on_its_own_prefix_and_never_writes_or_reloads_the_live_files():
    waf = gateway()

    assert crs.scratch_check(POSTURE, waf, WAF, 7) == []

    laid_out, tested, removed = waf.sent
    assert laid_out.stdin == crs.rendered(crs.checked(POSTURE))
    script = laid_out.argv[-1]
    assert "cp -a /etc/nginx/modsecurity /var/lib/cr-crstest/test-7/modsecurity" in script
    assert "SecAuditLog /var/lib/cr-crstest/test-7/logs/audit.log" in script
    assert script.endswith("cat > /var/lib/cr-crstest/test-7/modsecurity/crs/rules/"
                           "REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf")
    assert tested.argv[-1].startswith("nginx -t -p /var/lib/cr-crstest/test-7 -c /var/lib/cr-crstest/test-7/nginx.conf")
    assert "rm -rf /var/lib/cr-crstest/test-7" in removed.argv[-1]
    assert not any(f"cat > {WAF.rules}" in one.text or "nginx -s reload" in one.text for one in waf.sent)


def test_nginx_errors_come_back_with_their_lines():
    waf = FakeRunner().answer("nginx -t -p", (
        "nginx: [emerg] unknown directive \"SecRuel\" in /var/lib/cr-crstest/test-7/modsecurity/crs/x.conf:3\n"
        "nginx: configuration file /var/lib/cr-crstest/test-7/nginx.conf test failed\n"), 1)

    assert crs.scratch_check(POSTURE, waf, WAF, 7) == [{"line": 3, "message": 'unknown directive "SecRuel"'}]
    assert "rm -rf /var/lib/cr-crstest/test-7" in waf.sent[-1].text


def test_a_posture_the_validator_refuses_never_reaches_the_waf():
    waf = FakeRunner()

    with pytest.raises(crs.TuningRefused) as refused:
        crs.scratch_check({"paranoia": 9}, waf, WAF, 7)

    assert waf.sent == [] and refused.value.code == "crs_refused" and refused.value.status == 422


def test_the_scratch_test_replays_each_probe_to_loopback_and_reads_its_own_audit_log():
    waf = gateway()

    found = crs.scratch_test(POSTURE, waf, WAF, 7, PROBES)

    assert found == {
        "board-sqli-union": {"status": 403, "alerts": [
            {"rule": "942100", "signature": "SQL Injection Attack Detected via libinjection"},
            {"rule": "949110", "signature": "Inbound Anomaly Score Exceeded"}]},
        "board-normal-comment": {"status": 200, "alerts": []},
    }
    curls = [one for one in waf.sent if one.argv[0] == "curl"]
    assert [one.argv[-1] for one in curls] == ["http://127.0.0.1:18007/search/?q=1%27+UNION+SELECT",
                                               "http://127.0.0.1:18007/posts/1/comment/"]
    assert "X-Request-ID: board-sqli-union" in curls[0].argv and "Host: board.com" in curls[0].argv
    assert "Host: evil" not in curls[1].argv and curls[1].stdin == "body=hi"
    started = next(one for one in waf.sent if "probe-upstream.py" in one.text)
    assert "--port 19007" in started.text and json.loads(started.stdin) == PROBES
    assert "nginx -p /var/lib/cr-crstest/test-7 -c /var/lib/cr-crstest/test-7/nginx.conf" in started.text
    stopped = waf.sent[-1].text
    assert "-s stop" in stopped and "rm -rf /var/lib/cr-crstest/test-7" in stopped
    assert not any("nginx -s reload" in one.text or f"cat > {WAF.rules}" in one.text for one in waf.sent)


def test_a_scratch_config_nginx_refuses_is_a_refusal_with_field_errors_and_still_cleans_up():
    waf = FakeRunner().answer("nginx -t -p", "nginx: [emerg] bad in /x.conf:4", 1)

    with pytest.raises(crs.TuningRefused) as refused:
        crs.scratch_test(POSTURE, waf, WAF, 7, PROBES)

    assert crs.field_errors(refused.value) == [
        {"path": "posture", "code": "crs_refused", "line": 4, "params": {"message": "bad"}}]
    assert not any(one.argv[0] == "curl" for one in waf.sent)
    assert "rm -rf /var/lib/cr-crstest/test-7" in waf.sent[-1].text
