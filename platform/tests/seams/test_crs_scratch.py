import json

import pytest

from cr.config import WafConfig
from sandbox import crs
from testing.fakes import FakeRunner

WAF = WafConfig(reload="nginx -t 2>&1 && nginx -s reload 2>&1", pid="/run/nginx.pid")
EXCLUSIONS = "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
BOARD = "/etc/nginx/defence/board.com.conf"
FILES = {EXCLUSIONS: 'SecRule REQUEST_FILENAME "@beginsWith /search/" '
                     '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=942100;ARGS:q"\n',
         BOARD: "location /accounts/login/ {\n    limit_req zone=login;\n    proxy_pass http://board:8000;\n}\n"}
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


LIVE_FILES = 'base64 -w0 "$f" 2>/dev/null'
EMPTY_LIVE = "\n" * len(WAF.files)


def gateway():
    return (FakeRunner()
            .answer(LIVE_FILES, EMPTY_LIVE)
            .answer("nginx -t -p", "nginx: configuration file test is successful")
            .answer("board-sqli-union", "403")
            .answer("board-normal-comment", "200")
            .answer("audit.log", AUDIT))


def test_the_scratch_lives_apart_from_the_live_crs_tree_and_its_port_is_named_by_the_test():
    scratch = crs.scratch_for(WAF, 7)

    assert scratch.prefix == "/var/lib/cr-crstest/test-7"
    assert (scratch.port, scratch.upstream_port) == (18007, 19007)
    assert WAF.tree == "/etc/nginx/modsecurity"


@pytest.mark.parametrize("scratch", ["/etc/nginx/modsecurity", "/etc/nginx/modsecurity/crs/rules",
                                     "/etc/nginx/defence/scratch"])
def test_a_scratch_on_or_around_the_live_files_is_refused(scratch):
    with pytest.raises(ValueError):
        crs.scratch_for(WafConfig(scratch=scratch), 7)


def test_a_test_id_must_be_a_positive_number():
    with pytest.raises(ValueError):
        crs.scratch_for(WAF, 0)


def test_the_scratch_check_runs_nginx_t_on_its_own_prefix_and_never_writes_or_reloads_the_live_files():
    waf = gateway()

    assert crs.scratch_check(FILES, waf, WAF, 7) == []

    read_live, laid_out, exclusions, board, tested, removed = waf.sent
    assert read_live.argv[2] == crs.READ_FILES
    script = laid_out.argv[-1]
    assert "cp -a /etc/nginx/modsecurity /var/lib/cr-crstest/test-7/modsecurity" in script
    assert "cp -a /etc/nginx/defence /var/lib/cr-crstest/test-7/sites" in script
    assert "SecAuditLog /var/lib/cr-crstest/test-7/logs/audit.log" in script
    assert "proxy_pass http://127.0.0.1:19007;" in script, "the copied site files proxy to the probe stub, not the target"
    assert exclusions.argv[4] == ("/var/lib/cr-crstest/test-7/modsecurity/crs/rules/"
                                  "REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf") and exclusions.stdin == FILES[EXCLUSIONS]
    assert board.argv[4] == "/var/lib/cr-crstest/test-7/sites/board.com.conf"
    assert "proxy_pass http://127.0.0.1:19007;" in board.stdin and "board:8000" not in board.stdin
    assert tested.argv[-1].startswith("nginx -t -p /var/lib/cr-crstest/test-7 -c /var/lib/cr-crstest/test-7/nginx.conf")
    assert "rm -rf /var/lib/cr-crstest/test-7" in removed.argv[-1]
    assert not any(one.argv[4:5] in ([EXCLUSIONS], [BOARD]) or "nginx -s reload" in one.text for one in waf.sent)


def test_nginx_errors_come_back_with_the_live_file_and_line():
    waf = FakeRunner().answer(LIVE_FILES, EMPTY_LIVE).answer("nginx -t -p", (
        "nginx: [emerg] unknown directive \"limit_reqq\" in /var/lib/cr-crstest/test-7/sites/board.com.conf:2\n"
        "nginx: configuration file /var/lib/cr-crstest/test-7/nginx.conf test failed\n"), 1)

    assert crs.scratch_check(FILES, waf, WAF, 7) == [
        {"file": BOARD, "line": 2, "message": 'unknown directive "limit_reqq"'}]
    assert "rm -rf /var/lib/cr-crstest/test-7" in waf.sent[-1].text


def test_files_the_check_refuses_never_reach_the_waf():
    waf = FakeRunner()

    assert crs.scratch_check({"/etc/nginx/nginx.conf": ""}, waf, WAF, 7)[0]["file"] == "/etc/nginx/nginx.conf"
    assert waf.sent == []


def test_a_live_file_carrying_the_platform_s_logging_is_refused_before_the_scratch_loads_it():
    live = "\n".join("YWNjZXNzX2xvZyAvZXRjL2Nyb24uZC94Owo=" if path == WafConfig().files[3] else ""
                     for path in WAF.files)
    waf = FakeRunner().answer(LIVE_FILES, live)

    found = crs.scratch_check(FILES, waf, WAF, 7)

    assert [(one["file"], one["line"]) for one in found] == [("/etc/nginx/defence/http.conf", 1)]
    assert [one.argv[2] for one in waf.sent] == [crs.READ_FILES]


def test_the_scratch_test_replays_each_probe_to_loopback_and_reads_its_own_audit_log():
    waf = gateway()

    found = crs.scratch_test(FILES, waf, WAF, 7, PROBES)

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
    assert not any("nginx -s reload" in one.text or one.argv[4:5] == [EXCLUSIONS] for one in waf.sent)


def test_a_scratch_config_nginx_refuses_is_a_refusal_with_field_errors_and_still_cleans_up():
    waf = FakeRunner().answer("nginx -t -p", "nginx: [emerg] bad in /x.conf:4", 1)

    with pytest.raises(crs.WafRefused) as refused:
        crs.scratch_test(FILES, waf, WAF, 7, PROBES)

    assert [error.shown() for error in refused.value.errors] == [
        {"path": "/x.conf", "code": "crs_refused", "line": 4, "params": {"message": "bad"}}]
    assert not any(one.argv[0] == "curl" for one in waf.sent)
    assert "rm -rf /var/lib/cr-crstest/test-7" in waf.sent[-1].text
