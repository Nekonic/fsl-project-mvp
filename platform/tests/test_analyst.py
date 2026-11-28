import re
import subprocess
from pathlib import Path

import pytest

from cr.config import RELOAD_SNAPSHOTS, SensorConfig, WafConfig
from training.defence import terminal as service

ROOT = Path(__file__).resolve().parents[2]
WAF = ROOT / "deploy/roles/waf"
SCRIPT = WAF / "analyst.sh"


def text() -> str:
    return SCRIPT.read_text()


def assigned() -> dict[str, str]:
    return {name: value.strip('"') for name, value in re.findall(r'^([A-Z_]+)=("[^"]*"|\S+)$', text(), re.M)}


def printed(function: str) -> str:
    body = re.search(rf"^{function}\(\) \{{\n(.*?)^\}}\n", text(), re.M | re.S)[1].replace("\\\n", " ")
    [statement] = [line for line in body.splitlines() if line.strip().startswith("printf ")]
    without_redirect = re.sub(r'\s>\s*"\$\w+(?:\.new)?"\s*$', "", statement)
    names = "".join(f"{name}={value!r}; " for name, value in assigned().items() if " " not in value)
    return subprocess.run(["sh", "-c", names + without_redirect], capture_output=True, text=True, check=True).stdout


def test_the_account_is_the_one_the_defence_player_s_terminal_opens():
    assert assigned()["ACCOUNT"] == service.ANALYST_ACCOUNT == "analyst"
    assert "./analyst.sh" in (WAF / "install.sh").read_text()


def test_it_reads_the_logs_through_adm_and_logs_in_by_key_only():
    script = text()

    assert 'useradd --create-home --shell /bin/bash "$ACCOUNT"' in script
    assert "usermod --groups adm --password '*' \"$ACCOUNT\"" in script, (
        "adm reads /var/log/nginx and /var/log/modsecurity; '*' has no password but, unlike useradd's '!', "
        "does not lock the account against the jump grant's key")


def test_its_only_root_commands_are_the_nginx_test_dump_and_reload():
    rule = printed("nginx_checks_allowed")

    assert rule == ("analyst ALL=(root) NOPASSWD: /usr/local/sbin/nginx -t, /usr/local/sbin/nginx -T, "
                    "/usr/local/sbin/nginx -s reload, /usr/bin/systemctl reload nginx\n")
    assert "install -m 0755 nginx /usr/local/sbin/nginx" in (WAF / "install.sh").read_text(), (
        "sudo finds the reload wrapper first on its secure_path")
    assert (WAF / "nginx-reload.conf").read_text().splitlines()[-1] == "ExecReload=/usr/local/sbin/nginx -s reload"
    assert "ALL\n" not in rule
    assert 'visudo -cf "$SUDOERS.new"' in text()


def test_it_cannot_tunnel_through_its_ssh_login():
    match = printed("shell_only_over_ssh")

    assert match.startswith("Match User analyst\n")
    for setting in ("AllowTcpForwarding no", "AllowStreamLocalForwarding no", "AllowAgentForwarding no",
                    "X11Forwarding no", "PermitTunnel no"):
        assert f"    {setting}\n" in match


def test_it_reaches_only_the_waf_s_own_loopback_so_curl_tests_the_sites_through_the_waf():
    fence = printed("only_loopback_for_the_account")

    assert "table inet analyst {" in fence
    assert re.findall(r"^\s*(meta skuid .+)$", fence, re.M) == ['meta skuid analyst oif "lo" accept',
                                                               "meta skuid analyst drop"]
    assert "type filter hook output" in fence
    assert "systemctl enable nftables.service" in text()
    assert "nftables" in re.search(r"^installed (.+)", (WAF / "install.sh").read_text(), re.M)[1].split()


def test_it_writes_the_defence_files_and_nothing_else_of_the_nginx_crs_logging_or_log_shipping():
    script = text()
    defence = assigned()["DEFENCE_FILES"].replace("$CRS", assigned()["CRS"]).split()

    assert set(assigned()["READ_ONLY"].split()) == {"/etc/nginx", "/var/log/nginx", "/var/log/modsecurity",
                                                    "/etc/rsyslog.conf", "/etc/rsyslog.d", "/usr/local/share/slot"}
    assert '\\( -group adm -o -group "$ACCOUNT" \\) -perm -g+w -exec chmod g-w {} +' in script
    assert tuple(defence) == WafConfig().files, "the files the analyst may write are the ones the platform reads"
    assert 'chown root:"$ACCOUNT" "$file"' in script and 'chmod 0664 "$file"' in script
    assert script.index("\nnothing_writable_by_its_groups\n") < script.index("\ndefence_files_writable\n"), (
        "the defence files are made writable after every other file is made read-only")
    assert not any(file.endswith(("modsecurity.conf", "/conf.d/sites.conf")) for file in defence), (
        "log_format, access_log, the request marker and the audit log stay the platform's")
    assert (WAF / "install.sh").read_text().index("./analyst.sh") > (WAF / "install.sh").read_text().index(
        'install -m 0644 sites.conf'), "it runs after every nginx and CRS file is in place"


def test_it_is_posix_sh_that_stops_at_the_first_failure():
    assert text().startswith("#!/bin/sh\nset -eu\n")
    assert subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_the_site_config_keeps_the_logging_and_loads_the_defence_s_nginx_files_where_they_apply():
    site = (ROOT / "deploy/roles/waf/sites.conf").read_text()
    http_part, servers = site.split("\nserver {", 1)

    assert "log_format access" in http_part and "access_log /var/log/nginx/access.json access;" in http_part
    assert "include /etc/nginx/defence/http.conf;" in http_part
    assert "server_name board.com;\n    include /etc/nginx/defence/board.com.conf;" in servers
    assert "server_name corp.com;\n    include /etc/nginx/defence/corp.com.conf;" in servers
    assert "install -m 0644 sites.conf /etc/nginx/conf.d/sites.conf" in (WAF / "install.sh").read_text()


def test_the_platform_s_logging_lies_outside_what_the_analyst_writes():
    logging = (WAF / "sites.conf").read_text()
    defence = assigned()["DEFENCE_FILES"].replace("$CRS", assigned()["CRS"]).split()
    sensor = ROOT / "deploy/roles/infra"

    assert all(directive in logging for directive in ("log_format access", "access_log ", "error_log ",
                                                      "$http_x_request_id"))
    assert "install -m 0644 sites.conf /etc/nginx/conf.d/sites.conf" in (WAF / "install.sh").read_text()
    assert "/etc/nginx/conf.d/sites.conf" not in defence and "/etc/nginx" in assigned()["READ_ONLY"].split()
    assert "install -m 0644 suricata.yaml /etc/suricata/suricata.yaml" in (sensor / "install.sh").read_text()


@pytest.mark.parametrize(("role", "wrapper", "reloading", "snapshot", "loaded"), [
    ("waf", "nginx", '"$NGINX" -s reload', WafConfig().snapshot, WafConfig().files),
    ("infra", "suricatasc", "sensor suricatasc -c reload-rules)", SensorConfig(name="cr-ids").snapshot,
     (SensorConfig(name="cr-ids").rules,))])
def test_a_reload_snapshots_the_files_it_loads_where_the_analyst_cannot_write(role, wrapper, reloading, snapshot,
                                                                               loaded):
    script = (ROOT / "deploy/roles" / role / "analyst.sh").read_text()
    reload = (ROOT / "deploy/roles" / role / wrapper).read_text()
    names = dict(re.findall(r'^([A-Z_]+)=("[^"]*"|\S+)$', reload, re.M))
    listed = (names.get("DEFENCE_FILES") or names.get("RULE_FILE")).strip('"').replace("$CRS", names.get("CRS", ""))

    assert f"SNAPSHOT_DIR={RELOAD_SNAPSHOTS}\n" in script and names["SNAPSHOT"] == snapshot
    assert 'install -d -m 0700 -o root -g root "$SNAPSHOT_DIR"' in script
    assert script.rstrip().endswith("\nreload_snapshot_closed")
    assert tuple(listed.split()) == loaded, "the wrapper copies the files the platform reads back"
    assert reload.index('cp "$') < reload.index(reloading) < reload.index('mv "$staged" "$SNAPSHOT"'), (
        "the files are copied before the reload and the snapshot is kept only after it")
    assert reload.index('install -m 0644 -o root -g root "$staged') < reload.index(reloading), (
        "the engine loads the snapshot's copy, which the analyst cannot write until the reload is done")
    assert "trap handed_back EXIT" in reload and "trap '' INT TERM HUP" in reload
    assert 'flock 9' in reload and 'mktemp -d "$SNAPSHOT.new.XXXXXX"' in reload, "two reloads never share a snapshot"
    assert subprocess.run(["sh", "-n", str(ROOT / "deploy/roles" / role / wrapper)], capture_output=True).returncode == 0


WRAPPER_LINES = ["deny 203.0.113.9;", "access_log /etc/cron.d/x x;", "  log_format x '$remote_addr';",
                 "set_real_ip_from 127.0.0.1;", "real_ip_header X-Forwarded-For;", "include /home/analyst/x.conf;",
                 "  IncludeOptional /tmp/x.conf", "SecAuditEngine Off", "SecRule ARGS \"@rx x\" \"id:1,ctl:auditEngine=Off\"",
                 "# access_log off;", "limit_req zone=perip burst=5;", "SecRuleEngine DetectionOnly",
                 "location / { error_log /dev/null; }", "access_logging on;"]


@pytest.mark.parametrize("line", WRAPPER_LINES)
def test_the_reload_wrapper_refuses_what_the_console_refuses(tmp_path, line):
    from sandbox import crs

    wrapper = (WAF / "nginx").read_text()
    measured = re.search(r"^measured\(\) \{\n.*?^\}\n", wrapper, re.M | re.S)[0]
    given = tmp_path / "http.conf"
    given.write_text(line + "\n")

    ran = subprocess.run(["sh", "-c", measured + 'measured "$1"', "sh", str(given)], capture_output=True)

    assert (ran.returncode == 0) == bool(crs.measurement_in(str(given), line + "\n"))


def test_the_reload_wrapper_checks_the_snapshot_before_nginx_tests_or_loads_it_and_checks_a_bare_test_or_dump():
    wrapper = (WAF / "nginx").read_text()
    reload = wrapper[wrapper.index('trap handed_back EXIT'):]

    assert reload.index("refuse_measured $(for file in $DEFENCE_FILES; do echo \"$staged$file\"") < reload.index(
        '"$NGINX" -t')
    assert '-t|-T) refuse_measured $DEFENCE_FILES; exec "$NGINX" "$@" ;;' in wrapper


SEARCH_LINE = 'alert http any any -> any any (msg:"SQL"; content:"union"; sid:1;)\n'
IDS_LINES = ['alert http any any -> any any (msg:"x"; config: logging disable, tx, rule; sid:1;)',
             'alert http any any -> any any (msg:"x"; sid:2; \\\n  config:LOGGING disable, flow, rule;)',
             '# alert http any any -> any any (msg:"x"; config: logging disable, tx, rule; sid:3;)',
             'alert http any any -> any any (msg:"config: logging"; sid:4;)',
             'alert http any any -> any any (msg:"x"; content:"logging"; sid:5;)',
             'config logging disable tx rule']


@pytest.mark.parametrize("line", IDS_LINES)
def test_the_ids_reload_wrapper_refuses_what_the_platform_refuses(tmp_path, line):
    from sandbox import suricata

    wrapper = (ROOT / "deploy/roles/infra/suricatasc").read_text()
    measured = re.search(r"^measured\(\) \{\n.*?^\}\n", wrapper, re.M | re.S)[0]
    given = tmp_path / "local.rules"
    given.write_text(line + "\n")

    ran = subprocess.run(["sh", "-c", measured + 'measured "$1"', "sh", str(given)], capture_output=True)

    assert (ran.returncode == 0) == bool(suricata.refusals(line + "\n"))


def test_the_ids_reload_wrapper_checks_the_snapshot_before_it_loads_it():
    wrapper = (ROOT / "deploy/roles/infra/suricatasc").read_text()
    reload = wrapper[wrapper.index("trap handed_back EXIT"):]

    assert reload.index('measured "$staged$RULE_FILE"') < reload.index('install -m 0644 -o root -g root "$staged')


@pytest.mark.parametrize(("role", "wrapper", "passed"), [
    ("waf", "nginx", WafConfig().passed), ("infra", "suricatasc", SensorConfig(name="cr-ids").passed)])
def test_a_reload_reads_the_passed_tests_where_the_platform_lists_them(role, wrapper, passed):
    reload = (ROOT / "deploy/roles" / role / wrapper).read_text()

    assert f"PASSED={passed}\n" in reload


def test_the_waf_wrapper_hashes_a_snapshot_as_the_platform_lists_a_passed_test(tmp_path):
    from sandbox import crs

    wrapper = (WAF / "nginx").read_text()
    hashing = re.search(r"^loaded_sha\(\) \{\n.*?^\}\n", wrapper, re.M | re.S)[0]
    files = {path: f"# {path}\nSecRuleEngine On\n" if "setup" in path else "" for path in WafConfig().files}
    for path, text in files.items():
        (tmp_path / path.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path.lstrip("/")).write_text(text)
    listed = 'DEFENCE_FILES="' + " ".join(WafConfig().files) + '"\n'

    ran = subprocess.run(["sh", "-c", listed + hashing + 'loaded_sha "$1"', "sh", str(tmp_path)],
                         capture_output=True, text=True, check=True)

    assert ran.stdout.strip() == crs.loaded_sha(files)


def test_the_ids_wrapper_hashes_a_snapshot_as_the_platform_lists_a_passed_test(tmp_path):
    from sandbox import suricata

    wrapper = (ROOT / "deploy/roles/infra/suricatasc").read_text()
    hashing = re.search(r'grep -qxF "\$\((sha256sum < [^)]*)\)"', wrapper)[1]
    given = tmp_path / "local.rules"
    given.write_text(SEARCH_LINE)

    ran = subprocess.run(["sh", "-c", hashing.replace('"$staged$RULE_FILE"', '"$1"'), "sh", str(given)],
                         capture_output=True, text=True, check=True)

    assert ran.stdout.strip() == suricata.loaded_sha(SEARCH_LINE)


@pytest.mark.parametrize(("role", "wrapper", "check", "load"), [
    ("waf", "nginx", 'refuse_untested "$staged"', '"$NGINX" -t'),
    ("infra", "suricatasc", '"$PASSED"', 'install -m 0644 -o root -g root "$staged')])
def test_a_reload_refuses_a_snapshot_no_passed_test_lists_before_it_loads_it(role, wrapper, check, load):
    reload = (ROOT / "deploy/roles" / role / wrapper).read_text()
    staged = reload[reload.index("trap handed_back EXIT"):]

    assert staged.index(check) < staged.index(load)
    assert "테스트를 통과한" in reload and "반영하지 않았습니다" in reload
