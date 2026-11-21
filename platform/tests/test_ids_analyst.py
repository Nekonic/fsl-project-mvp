import re
import subprocess
from pathlib import Path

import pytest

from sandbox import stack_plan
from training.defence import terminal as service

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "deploy/roles/infra"
SCRIPT = INFRA / "analyst.sh"
WARGAMES = sorted(path.parent.name for path in (ROOT / "wargames").glob("*/topology.yaml"))


def text() -> str:
    return SCRIPT.read_text()


def install() -> str:
    return (INFRA / "install.sh").read_text()


def assigned() -> dict[str, str]:
    return {name: value.strip('"') for name, value in re.findall(r'^([A-Z_]+)=("[^"]*"|\S+)$', text(), re.M)}


def body_of(function: str) -> str:
    return re.search(rf"^{function}\(\) \{{\n(.*?)^\}}\n", text(), re.M | re.S)[1].replace("\\\n", " ")


def printed(function: str) -> str:
    [statement] = [line for line in body_of(function).splitlines() if line.strip().startswith("printf ")]
    without_redirect = re.sub(r'\s>\s*"\$\w+(?:\.new)?"\s*$', "", statement)
    names = "".join(f"{name}={value!r}; " for name, value in assigned().items() if " " not in value)
    return subprocess.run(["sh", "-c", names + without_redirect], capture_output=True, text=True, check=True).stdout


def test_the_sensor_s_analyst_is_the_account_the_ids_terminal_opens_and_reads_the_eve_log_through_adm():
    assert assigned()["ACCOUNT"] == service.ANALYST_ACCOUNT
    assert "usermod --groups adm --password '*' \"$ACCOUNT\"" in text()
    assert "install -d -m 2750 -g adm \"$EVE_DIR\"" in install()
    assert install().index("./analyst.sh") > install().index("customers_installed\n"), (
        "it runs after the rule file, the router's files and the customers' program are in place")


@pytest.mark.parametrize("wargame", WARGAMES)
def test_its_only_root_commands_are_the_rule_test_and_the_reload_the_topology_names(wargame):
    sensor = stack_plan.read(ROOT, wargame).filling("sensor")

    assert printed("sensor_checks_allowed") == (
        f"analyst ALL=(root) NOPASSWD: /usr/local/bin/suricata -T, /usr/local/bin/{sensor.reload}\n")
    assert 'visudo -cf "$SUDOERS.new"' in text()
    assert "install -m 0755 suricata /usr/local/bin/suricata" in install()
    assert (INFRA / "suricata").read_text().splitlines()[-1] == (
        "exec docker exec sensor suricata -T -c /etc/suricata/suricata.yaml -l /tmp")


@pytest.mark.parametrize("wargame", WARGAMES)
def test_it_writes_the_rule_file_the_topology_names_and_nothing_of_the_sensor_s_configuration_or_logs(wargame):
    sensor = stack_plan.read(ROOT, wargame).filling("sensor")
    written = body_of("rule_file_writable")

    assert assigned()["RULE_FILE"] == sensor.rules
    assert 'setfacl -m "u:$ACCOUNT:rw" "$RULE_FILE"' in written, (
        "the sensor's start chowns the rules tree to its own user, which keeps an ACL but not a group")
    assert "acl" in re.search(r"^installed (.+)", install(), re.M)[1].split()
    assert set(assigned()["READ_ONLY"].split()) == {"/etc/suricata", "/var/lib/suricata", "/var/log/suricata",
                                                    "/etc/rsyslog.conf", "/etc/rsyslog.d"}
    assert text().index("\nnothing_writable_by_its_groups\n") < text().index("\nrule_file_writable\n")


def test_it_has_no_way_into_the_router_the_customers_or_docker():
    assert set(assigned()["CLOSED"].split()) == {"/usr/local/share/slot", "/var/lib/cr-ruletest"}
    assert 'chmod 0700 "$tree"' in body_of("router_and_customers_closed")
    assert 'install -d -m 0750 -o "$CUSTOMERS_ACCOUNT" -g "$CUSTOMERS_ACCOUNT" "$CUSTOMERS_HOME"' in install()
    assert 'install -d -m 0750 -g "$CUSTOMERS_ACCOUNT" "$CUSTOMERS_PROGRAM_DIR"' in install()
    assert "docker" not in body_of("account_made") and "cr-users" not in text()


def test_it_cannot_tunnel_and_reaches_only_loopback_addresses_so_not_the_log_relay_on_the_host_s_own_address():
    match = printed("shell_only_over_ssh")
    fence = printed("only_loopback_for_the_account")
    relay = (INFRA / "log-relay.conf").read_text()

    assert match.startswith("Match User analyst\n") and "    AllowTcpForwarding no\n" in match
    assert re.findall(r"^\s*(meta skuid .+)$", fence, re.M) == [
        'meta skuid analyst oif "lo" ip daddr 127.0.0.0/8 accept',
        'meta skuid analyst oif "lo" ip6 daddr ::1 accept',
        "meta skuid analyst drop"]
    assert 'input(type="imtcp" address="@log_server@" port="514"' in relay, (
        "the relay forwards what it hears as WAF logs; it listens on the host's own address, which the fence drops")
    assert "flush ruleset" not in fence, "the edge table slot-boot loads must survive nftables.service"
    assert "systemctl disable nftables.service" not in install()


def test_it_is_posix_sh_that_stops_at_the_first_failure():
    assert text().startswith("#!/bin/sh\nset -eu\n")
    assert subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True).returncode == 0
