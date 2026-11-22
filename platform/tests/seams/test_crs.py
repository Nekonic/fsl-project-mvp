import pytest

from cr import config
from sandbox import crs
from sandbox.runner import Ran
from testing.fakes import Gateway

WAF = config.WafConfig()
RELOAD = ["sh", "-c", WAF.reload]
SETUP, EXCLUSIONS, AFTER, HTTP, BOARD, CORP = WAF.files
EXCLUDE_Q = ('SecRule REQUEST_FILENAME "@beginsWith /search/" '
             '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=942100;ARGS:q"\n')


class Workers(Gateway):
    def __init__(self, workers, **given):
        super().__init__(**given)
        self.seen = list(workers)
        self.reads = 0

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[-1] == crs.workers_of(WAF.pid):
            self.reads += 1
            return Ran(0, self.seen[min(self.reads, len(self.seen)) - 1])
        return super().__call__(argv, stdin, timeout)


def written(gateway) -> list[str]:
    return [one.argv[4] for one in gateway.sent if one.argv[:3] == ["sh", "-c", crs.WRITE_FILE]]


def test_the_defence_edits_crs_setup_both_exclusion_files_and_the_nginx_files_beside_the_platform_s_logging():
    assert WAF.files == (
        "/etc/nginx/modsecurity/crs/crs-setup.conf",
        "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf",
        "/etc/nginx/modsecurity/crs/rules/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf",
        "/etc/nginx/defence/http.conf", "/etc/nginx/defence/board.com.conf", "/etc/nginx/defence/corp.com.conf")
    assert config.build({}).waf.files == WAF.files, "the topology's WAF device names the same files"


def test_the_files_are_read_in_one_call_whole():
    gateway = Gateway(files={**Gateway().files, HTTP: "limit_req_zone $binary_remote_addr zone=ip:10m rate=5r/s;\n",
                             EXCLUSIONS: "한 줄\n"})

    assert crs.read(gateway, WAF) == {**{path: "" for path in WAF.files},
                                      HTTP: "limit_req_zone $binary_remote_addr zone=ip:10m rate=5r/s;\n",
                                      EXCLUSIONS: "한 줄\n"}
    assert len(gateway.sent) == 1


def test_a_waf_that_cannot_be_read_is_unavailable():
    with pytest.raises(crs.WafUnreadable):
        crs.read(lambda argv, stdin=None, timeout=60.0: Ran(255, "ssh: connect refused"), WAF)


def test_applying_writes_only_the_changed_files_and_reloads_nginx():
    gateway = Gateway()

    merged = crs.apply({EXCLUSIONS: EXCLUDE_Q, HTTP: ""}, gateway, WAF)

    assert merged == {**{path: "" for path in WAF.files}, EXCLUSIONS: EXCLUDE_Q}
    assert gateway.files[EXCLUSIONS] == EXCLUDE_Q
    assert written(gateway) == [EXCLUSIONS]
    sent = [one.argv for one in gateway.sent]
    assert [argv for argv in sent if argv == RELOAD] == [RELOAD]
    assert sent.index(RELOAD) > max(at for at, argv in enumerate(sent) if argv[:3] == ["sh", "-c", crs.WRITE_FILE])


def test_files_nginx_refuses_are_rolled_back_and_refused_with_the_file_and_line():
    gateway = Gateway(files={**Gateway().files, HTTP: "deny 203.0.113.9;\n"}, reload_fails='unknown directive "x"')

    with pytest.raises(crs.WafRefused) as refused:
        crs.apply({HTTP: "x;\n"}, gateway, WAF)

    assert gateway.files[HTTP] == "deny 203.0.113.9;\n"
    assert [error.shown() for error in refused.value.errors] == [
        {"path": HTTP, "code": "crs_refused", "line": 2, "params": {"message": 'unknown directive "x"'}}]


@pytest.mark.parametrize("files, path, line", [
    ({"/etc/nginx/nginx.conf": ""}, "/etc/nginx/nginx.conf", None),
    ({HTTP: "deny all;\naccess_log off;\n"}, HTTP, 2),
    ({BOARD: "  log_format mine '$remote_addr';\n"}, BOARD, 1),
    ({CORP: "error_log /dev/null;\n"}, CORP, 1),
    ({SETUP: "SecAuditEngine Off\n"}, SETUP, 1),
    ({AFTER: "SecRule ARGS \"@rx x\" \"id:1,ctl:auditEngine=Off,ctl:auditLogParts=+E\"\n"}, AFTER, None),
    ({BOARD: "modsecurity_rules 'SecAuditLog /tmp/x';\n"}, BOARD, 1),
    ({BOARD: "location / { access_log off; proxy_pass http://10.30.128.59; }\n"}, BOARD, 1),
    ({HTTP: "set_real_ip_from 127.0.0.1;\n"}, HTTP, 1),
    ({HTTP: "deny all; real_ip_header X-Forwarded-For;\n"}, HTTP, 1),
    ({BOARD: "real_ip_recursive on;\n"}, BOARD, 1),
    ({EXCLUSIONS: 7}, EXCLUSIONS, None),
])
def test_a_file_the_defence_does_not_edit_or_a_logging_directive_never_reaches_the_waf(files, path, line):
    gateway = Gateway()

    with pytest.raises(crs.WafRefused) as refused:
        crs.apply(files, gateway, WAF)

    assert refused.value.errors[0].path == path
    if line:
        assert refused.value.errors[0].line == line
    assert gateway.sent == []


def test_a_logging_directive_left_unloaded_in_a_live_file_is_refused_before_a_console_apply_reloads_it():
    gateway = Gateway(files={**Gateway().files, HTTP: "access_log /etc/cron.d/x;\n"})

    with pytest.raises(crs.WafRefused) as refused:
        crs.apply({BOARD: "deny 203.0.113.9;\n"}, gateway, WAF)

    assert (refused.value.errors[0].path, refused.value.errors[0].line) == (HTTP, 1)
    assert written(gateway) == [] and [one.argv for one in gateway.sent if one.argv == RELOAD] == []


@pytest.mark.parametrize("text", ["include /home/analyst/x.conf;\n", "http { include x; }\n",
                                  "  IncludeOptional /tmp/x.conf\n"])
def test_an_include_is_refused_because_it_loads_a_file_the_platform_does_not_check(text):
    assert [one["line"] for one in crs.refusals({HTTP: text}, WAF)] == [1]


def test_a_logging_word_in_a_comment_is_not_refused():
    assert crs.refusals({HTTP: "deny 203.0.113.9; # access_log stays as the platform set it\n"}, WAF) == []


@pytest.mark.parametrize("text", ["SecRuleEngine Off\n", "SecRuleEngine DetectionOnly\n",
                                  "SecAction \"id:900000,phase:1,pass,t:none,nolog,setvar:tx.blocking_paranoia_level=3\"\n"])
def test_the_rule_engine_and_the_paranoia_level_are_the_defence_s_to_set(text):
    assert crs.refusals({SETUP: text}, WAF) == []


def test_applying_returns_once_a_new_nginx_worker_serves_without_waiting_for_old_ones_to_drain(monkeypatch):
    monkeypatch.setattr(crs.time, "sleep", lambda seconds: None)
    settled = Workers(["11 12", "11 12", "11 12 21 22", "12 21 22"])

    crs.apply({HTTP: "deny 203.0.113.9;\n"}, settled, WAF)

    assert settled.reads == 3, "the third read is the first to list a new worker, 21, while old 11 still serves"
    assert written(settled) == [HTTP], "no rollback is written while the old worker drains"


def test_a_reload_that_starts_no_new_worker_is_rolled_back_and_refused(monkeypatch):
    monkeypatch.setattr(crs.time, "sleep", lambda seconds: None)
    stuck = Workers(["11 12"], files={**Gateway().files, HTTP: "the previous file\n"})

    with pytest.raises(crs.WafRefused, match="no worker"):
        crs.apply({HTTP: "deny all;\n"}, stuck, WAF)

    assert stuck.files[HTTP] == "the previous file\n"
    assert stuck.sent[-1].argv == RELOAD, "the previous files are reloaded"


def test_on_openstack_the_files_are_written_where_the_waf_vm_reads_them_and_its_nginx_reloads():
    layout = config.build({}).waf
    gateway = Gateway()

    crs.apply({SETUP: "SecRuleEngine DetectionOnly\n"}, gateway, layout)

    assert written(gateway) == [SETUP]
    assert layout.pid == "/run/nginx.pid"
    assert layout.reload == "nginx -t 2>&1 && nginx -s reload 2>&1", "nginx runs in the foreground, with no systemd"


def test_detection_only_appends_the_rule_engine_to_crs_setup_and_keeps_the_rest():
    files = {**{path: "" for path in WAF.files}, SETUP: "SecRuleEngine On", HTTP: "deny all;\n"}

    assert crs.detection_only(files, WAF) == {**files, SETUP: "SecRuleEngine On\nSecRuleEngine DetectionOnly\n"}


def test_nginx_and_modsecurity_errors_name_the_file_and_line():
    said = ('nginx: [emerg] "modsecurity_rules_file" directive Rules error. '
            'File: /var/lib/cr-crstest/test-7/modsecurity/crs/crs-setup.conf. Line: 4. Column: 9. '
            'Invalid input: SecRuleEngin On in /var/lib/cr-crstest/test-7/nginx.conf:21\n'
            'nginx: [emerg] unknown directive "denyy" in /var/lib/cr-crstest/test-7/sites/http.conf:2\n')

    assert crs.nginx_errors(said, {"/var/lib/cr-crstest/test-7/modsecurity": WAF.tree,
                                   "/var/lib/cr-crstest/test-7/sites": WAF.sites}) == [
        {"file": SETUP, "line": 4, "message": said.splitlines()[0].split("] ", 1)[1].rsplit(" in ", 1)[0]},
        {"file": HTTP, "line": 2, "message": 'unknown directive "denyy"'}]


def test_the_limit_rates_are_read_from_the_waf_files_in_requests_per_minute():
    files = ("#limit_req_zone $binary_remote_addr zone=old:10m rate=1r/s;\n"
             "limit_req_zone $binary_remote_addr zone=perip:10m rate=2r/s;\n"
             "limit_req_zone $binary_remote_addr rate=30r/m zone=slow:1m;\n"
             "server { location / { limit_req zone=perip burst=5; } }\n")

    assert crs.limit_rates_in(files) == {"perip": 120, "slow": 30}


def test_a_zone_not_keyed_by_the_client_s_address_has_no_rate_a_refusal_can_be_judged_by():
    dumped = ("limit_req_zone $server_name zone=all:1m rate=90r/m;\n"
              "limit_req_zone \"constant\" zone=one:1m rate=90r/m;\n"
              "limit_req_zone $binary_remote_addr$uri zone=perpage:1m rate=90r/m;\n")

    assert crs.limit_rates_in(dumped) == {"perpage": 90}
