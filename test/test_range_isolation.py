import ipaddress
import json
import os
import re
import shlex
import time
import uuid
from urllib.parse import urlsplit

import pytest
import requests

from conftest import PLATFORM_URL
from range import ATTACKER, BOARD, run

GATEWAY = "gateway"
RANGE_HOST = "wargames"
PROBERS = (ATTACKER, GATEWAY, BOARD)
ESTATE = re.compile(r"inet (10\.\d+\.(\d+)\.\d+)/24")
COLLECTOR = re.compile(r'Target="([\d.]+)"')
HOST_PORT = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\S+)", re.M)
CONTAINER_SIDE = re.compile(r"^(lo|docker\d+|br-\w+|veth\w*|s\d+-\w+)$")
SERVICE_PORTS = "22,80,443,3306,5140,5601,8000,8080,9200"
OPEN_PORT = re.compile(r"^(\d+)/tcp\s+open\b", re.M)
SCANNED_HOST = re.compile(r"^Nmap scan report for (\S+)", re.M)
ELASTIC = "http://localhost:9200"
CANARY = "/var/log/cr-isolation-canary.log"
WAF_AUDIT = "/var/log/modsecurity/audit"
SHIPPED_WITHIN = 180
PLANTED_WAIT = 60
SETTLE_WAIT = 1800


def reached(role: str, address: str, port: int) -> bool:
    return run(role, ["timeout", "5", "bash", "-c", f"exec 3<>/dev/tcp/{address}/{port}"]).exit_code == 0


@pytest.fixture(scope="module")
def facts():
    waf = run(GATEWAY, ["ip", "-o", "-4", "addr", "show"]).stdout
    own_address, own_slot = ESTATE.search(waf).groups()
    ports = HOST_PORT.findall(run(RANGE_HOST, ["ip", "-o", "-4", "addr", "show"]).stdout)
    host = [address for _, address in ports]
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
        "host_networks": sorted({str(ipaddress.ip_interface(address).network) for name, address in ports
                                 if not CONTAINER_SIDE.match(name)}),
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


def _open_services(targets: list[str]) -> dict[str, list[str]]:
    scan = run(ATTACKER, ["sh", "-c",
                          f"$(command -v sudo >/dev/null && echo sudo -n) nmap -n -Pn -sT --open -T4 "
                          f"--max-retries 1 --max-rtt-timeout 500ms --host-timeout 90s "
                          f"-p {SERVICE_PORTS} {' '.join(targets)}"], timeout=900).stdout
    reports = SCANNED_HOST.split(scan)
    return {host: OPEN_PORT.findall(body) for host, body in zip(reports[1::2], reports[2::2])
            if OPEN_PORT.findall(body)}


def test_the_attacker_reaches_no_service_on_the_range_host_the_platform_or_their_network(facts):
    targets = sorted({*facts["range_host"], *facts["platform"], *facts["host_networks"]})

    reached = _open_services(targets)

    assert facts["host_networks"] and not reached, (
        f"Kali reaches {reached} beyond its route to the sites; the range host, the platform and the "
        f"management network they share take nothing from a slot")


def _shipped(probe: str) -> list[str]:
    found = requests.post(f"{ELASTIC}/logs-*-sensors/_search",
                          json={"size": 20, "query": {"match_phrase": {"cr_probe": probe}}}, timeout=30).json()
    return [hit["_index"] for hit in found.get("hits", {}).get("hits", [])]


def _shipped_within(probe: str, seconds: float) -> list[str]:
    deadline = time.monotonic() + seconds
    while not (indices := _shipped(probe)) and time.monotonic() < deadline:
        time.sleep(3)
    return indices


def _settled_after_close(slot: str) -> dict:
    deadline = time.monotonic() + SETTLE_WAIT
    while True:
        every = requests.get(f"{PLATFORM_URL}/api/range/ready/", timeout=60).json().get("slots") or []
        mine = next((each for each in every if str(each.get("number")) == slot), {})
        settled = (mine.get("session") is None and (mine.get("reset") or {}).get("state") != "running"
                   and mine.get("phase") not in ("RESETTING", "REBUILDING", "CHECKING"))
        if settled or time.monotonic() > deadline:
            return mine
        time.sleep(5)


def test_a_link_planted_in_the_waf_neither_reaches_a_host_file_at_reset_nor_ships_another_log():
    token = uuid.uuid4().hex
    canary = json.dumps({"cr_probe": f"canary-{token}"})
    own = json.dumps({"cr_probe": f"own-{token}"})
    opened = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600)
    assert opened.status_code == 201, opened.text
    session = opened.json()["id"]
    try:
        slot = ESTATE.search(run(GATEWAY, ["ip", "-o", "-4", "addr", "show"], session=session).stdout)[2]
        host_log = f"/var/log/cr/s{slot}/waf"
        written = run(RANGE_HOST, ["sudo", "sh", "-c", f"printf '%s\\n' {shlex.quote(canary)} > {CANARY} "
                                   f"&& chmod 0644 {CANARY} && ls /var/log/cr"], session=session)
        assert written.ok, written.output
        other = next((name for name in written.stdout.split() if name != f"s{slot}"), "s0")
        waf_before = run(RANGE_HOST, ["sudo", "docker", "inspect", "-f", "{{.State.StartedAt}}",
                                      f"s{slot}-waf"], session=session).stdout.strip()
        wrote = run(GATEWAY, ["sh", "-c", f"printf '%s\\n' {shlex.quote(own)} >> {WAF_AUDIT}/audit.log"],
                    session=session)
        shipped_own = _shipped_within(f"own-{token}", SHIPPED_WITHIN)
        assert shipped_own == [f"logs-{slot}-sensors"], (
            f"a line the WAF wrote to its audit log did not reach slot {slot}'s index ({shipped_own}), "
            f"so the rest of this test would prove nothing: {wrote.output[-300:]}")

        planted = run(GATEWAY, ["sh", "-c",
                                f"cd {WAF_AUDIT}; ln -sf {CANARY} audit.log; ln -s {CANARY} planted; "
                                f"ln -s /var/log/cr/{other}/waf/audit.log other; ln -s /etc/passwd passwd; "
                                f"ls -la"], session=session)

        assert not _shipped_within(f"canary-{token}", PLANTED_WAIT), (
            f"a host file reached Elasticsearch after the WAF planted links to it: {planted.output[-600:]}")
    finally:
        closed = requests.post(f"{PLATFORM_URL}/api/sessions/{session}/close/", json={}, timeout=120)
    assert closed.status_code == 200, closed.text

    settled = _settled_after_close(slot)
    host = run(RANGE_HOST, ["sudo", "sh", "-c",
                            f"cat {CANARY}; echo --; find {host_log} -mindepth 1 -printf '%f %y %u\\n'; "
                            f"stat -c '%U %a' {host_log}; echo --; "
                            f"docker inspect -f '{{{{.State.StartedAt}}}}' s{slot}-waf; rm -f {CANARY}"])
    kept, listed, started = host.stdout.split("--\n")

    assert settled.get("phase") == "READY", f"slot {slot} did not settle after its reset: {settled}"
    assert started.strip() != waf_before, f"slot {slot}'s WAF was not recreated, so no reset ran"
    assert kept.strip() == canary, f"the reset wrote through a link the learner planted: {CANARY} is now {kept!r}"
    entries = listed.strip().splitlines()
    assert entries[0].startswith("audit.log f ") and entries[1:] == ["root 755"], (
        f"the WAF's log directory on the range host holds more than its own log file: {listed}")
    assert not _shipped(f"canary-{token}"), "a host file reached Elasticsearch after the reset"
