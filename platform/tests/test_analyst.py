import re
import subprocess
from pathlib import Path

from cr.config import WafConfig
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

    assert rule == ("analyst ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /usr/sbin/nginx -T, /usr/sbin/nginx -s reload, "
                    "/usr/bin/systemctl reload nginx\n")
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
    assert not any(file.endswith(("modsecurity.conf", "/conf.d/board.com.conf")) for file in defence), (
        "log_format, access_log, the request marker and the audit log stay the platform's")
    assert (WAF / "install.sh").read_text().index("./analyst.sh") > (WAF / "install.sh").read_text().index(
        'install -m 0644 board.com.conf'), "it runs after every nginx and CRS file is in place"


def test_it_is_posix_sh_that_stops_at_the_first_failure():
    assert text().startswith("#!/bin/sh\nset -eu\n")
    assert subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_the_site_config_keeps_the_logging_and_loads_the_defence_s_nginx_files_where_they_apply():
    site = (ROOT / "deploy/waf/board.com.conf").read_text()
    http_part, servers = site.split("\nserver {", 1)

    assert "log_format access" in http_part and "access_log /var/log/nginx/access.json access;" in http_part
    assert "include /etc/nginx/defence/http.conf;" in http_part
    assert "server_name board.com;\n    include /etc/nginx/defence/board.com.conf;" in servers
    assert "server_name corp.com;\n    include /etc/nginx/defence/corp.com.conf;" in servers
    assert "install -m 0644 board.com.conf /etc/nginx/conf.d/board.com.conf" in (WAF / "install.sh").read_text()
