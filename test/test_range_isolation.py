import ipaddress
import os
import re
from urllib.parse import urlsplit

import pytest

from range import ATTACKER, BOARD, run

GATEWAY = "gateway"
RANGE_HOST = "wargames"
PROBERS = (ATTACKER, GATEWAY, BOARD)
ESTATE = re.compile(r"inet (10\.\d+\.(\d+)\.\d+)/24")
COLLECTOR = re.compile(r'Target="([\d.]+)"')


def reached(role: str, address: str, port: int) -> bool:
    return run(role, ["timeout", "5", "bash", "-c", f"exec 3<>/dev/tcp/{address}/{port}"]).exit_code == 0


@pytest.fixture(scope="module")
def facts():
    waf = run(GATEWAY, ["ip", "-o", "-4", "addr", "show"]).stdout
    own_address, own_slot = ESTATE.search(waf).groups()
    host = run(RANGE_HOST, ["sh", "-c", "ip -o -4 addr show | awk '{print $4}'"]).stdout.split()
    names = run(RANGE_HOST, ["sudo", "docker", "ps", "--format", "{{.Names}}"]).stdout.split()
    others = [name for name in names if re.fullmatch(r"s\d+-waf", name) and name != f"s{own_slot}-waf"]
    other_wafs = [run(RANGE_HOST, ["sudo", "docker", "inspect", "-f",
                                   "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", name]).stdout.split()[0]
                  for name in others]
    forwarded = run(RANGE_HOST, ["sh", "-c", "cat /etc/rsyslog.d/60-cr-*.conf"]).stdout
    return {
        "slot": own_slot,
        "waf": own_address,
        "board": own_address.rsplit(".", 1)[0] + ".59",
        "range_host": [str(ipaddress.ip_interface(one).ip) for one in host
                       if not ipaddress.ip_interface(one).ip.is_loopback],
        "platform": sorted({urlsplit(os.environ.get("CR_PLATFORM_URL", "")).hostname or "",
                            *COLLECTOR.findall(forwarded)} - {"", "localhost", "127.0.0.1"}),
        "other_slots": other_wafs,
    }


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_range_host_itself(facts, role):
    reaching = [address for address in facts["range_host"] if reached(role, address, 22)]

    assert not reaching, (
        f"{role} reaches the range host's sshd at {reaching}; a root shell one step from the host "
        f"that runs every other slot")


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_platform(facts, role):
    reaching = [f"{address}:{port}" for address in facts["platform"] for port in (8000, 22)
                if reached(role, address, port)]

    assert facts["platform"] and not reaching, f"{role} reaches the platform at {reaching}"


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_internet_or_the_cloud_s_metadata(role):
    reaching = [target for target, port in (("1.1.1.1", 443), ("169.254.169.254", 80)) if reached(role, target, port)]

    assert not reaching, f"{role} leaves the range for {reaching}"


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_another_slot(facts, role):
    reaching = [address for address in facts["other_slots"] if reached(role, address, 80)]

    assert not reaching, f"{role} in slot {facts['slot']} reaches another slot's WAF at {reaching}"


def test_the_attacker_reaches_the_sites_through_the_waf_and_the_board_through_the_edge(facts):
    assert reached(ATTACKER, facts["waf"], 80), "the attack has no way in at all"
    assert reached(ATTACKER, facts["board"], 8000), (
        "the board stands behind the edge, not behind the WAF alone, as on the VM range")
    assert run(ATTACKER, ["getent", "hosts", "board-db"]).exit_code != 0, "the database is named only on its own network"


def test_the_attacker_s_syn_scan_runs_with_the_capabilities_its_container_holds(facts):
    scan = run(ATTACKER, ["nmap", "-n", "-Pn", "-sS", "-p", "80", facts["waf"]], timeout=120)

    assert re.search(r"^80/tcp\s+open\b", scan.stdout, re.M), (
        f"a SYN scan needs raw sockets, which NET_RAW in the Kali container gives root: {scan.stdout[-400:]}")
