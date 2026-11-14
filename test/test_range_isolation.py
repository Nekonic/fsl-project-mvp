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

from conftest import PLATFORM_URL, STANDING
from range import ATTACKER, BOARD, run, run_side_by_side

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
SKIPPED_HOST = re.compile(r"^Skipping host (\S+) due to host timeout", re.M)
ELASTIC = "http://localhost:9200"
CANARY = "/var/log/cr-isolation-canary.log"
WAF_AUDIT = "/var/log/modsecurity/audit"
SHIPPED_WITHIN = 180
PLANTED_WAIT = 60
SETTLE_WAIT = 1800


def connect(address: str, port: int) -> list[str]:
    return ["timeout", "5", "bash", "-c", f"exec 3<>/dev/tcp/{address}/{port}"]


@pytest.fixture(scope="module")
def facts():
    waf = run(GATEWAY, ["ip", "-o", "-4", "addr", "show"]).stdout
    own_address, own_slot = ESTATE.search(waf).groups()
    host = run_side_by_side(RANGE_HOST, {
        "ports": ["ip", "-o", "-4", "addr", "show"],
        "names": ["sudo", "docker", "ps", "--format", "{{.Names}}"],
        "forwarded": ["sh", "-c", "cat /etc/rsyslog.d/60-cr-*.conf"],
    })
    ports = HOST_PORT.findall(host["ports"].stdout)
    others = [name for name in host["names"].stdout.split()
              if re.fullmatch(r"s\d+-waf", name) and name != f"s{own_slot}-waf"]
    other_wafs = run(RANGE_HOST, ["sudo", "docker", "inspect", "-f",
                                  "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", *others]
                     ).stdout.split() if others else []
    return {
        "slot": own_slot,
        "waf": own_address,
        "board": own_address.rsplit(".", 1)[0] + ".59",
        "range_host": [str(ipaddress.ip_interface(one).ip) for _, one in ports
                       if not ipaddress.ip_interface(one).ip.is_loopback],
        "platform": sorted({urlsplit(os.environ.get("CR_PLATFORM_URL", "")).hostname or "",
                            *COLLECTOR.findall(host["forwarded"].stdout)} - {"", "localhost", "127.0.0.1"}),
        "other_slots": other_wafs,
        "host_networks": sorted({str(ipaddress.ip_interface(address).network) for name, address in ports
                                 if not CONTAINER_SIDE.match(name)}),
    }


def probes(facts) -> dict[str, list[tuple[str, int]]]:
    return {
        "range host": [(address, 22) for address in facts["range_host"]],
        "platform": [(address, port) for address in facts["platform"] for port in (8000, 22)],
        "outside": [("1.1.1.1", 443), ("169.254.169.254", 80)],
        "other slots": [(address, 80) for address in facts["other_slots"]],
        "way in": [(facts["waf"], 80), (facts["board"], 8000)],
    }


@pytest.fixture(scope="module")
def reached(facts):
    found = {}
    for role in PROBERS:
        targets = sorted({target for what, listed in probes(facts).items() for target in listed
                          if what != "way in" or role == ATTACKER})
        ran = run_side_by_side(role, {target: connect(*target) for target in targets}, timeout=120)
        found[role] = {target for target, result in ran.items() if result.ok}
    return found


def reaching(reached, facts, role: str, what: str) -> list[str]:
    return [f"{address}:{port}" for address, port in probes(facts)[what] if (address, port) in reached[role]]


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_range_host_itself(reached, facts, role):
    found = reaching(reached, facts, role, "range host")

    assert not found, (
        f"{role} reaches the range host's sshd at {found}; a root shell one step from the host "
        f"that runs every other slot")


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_platform(reached, facts, role):
    found = reaching(reached, facts, role, "platform")

    assert facts["platform"] and not found, f"{role} reaches the platform at {found}"


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_the_internet_or_the_cloud_s_metadata(reached, facts, role):
    found = reaching(reached, facts, role, "outside")

    assert not found, f"{role} leaves the range for {found}"


@pytest.mark.parametrize("role", PROBERS)
def test_no_container_reaches_another_slot(reached, facts, role):
    found = reaching(reached, facts, role, "other slots")

    assert not found, f"{role} in slot {facts['slot']} reaches another slot's WAF at {found}"


def test_the_attacker_reaches_the_sites_through_the_waf_and_the_board_through_the_edge(reached, facts):
    assert (facts["waf"], 80) in reached[ATTACKER], "the attack has no way in at all"
    assert (facts["board"], 8000) in reached[ATTACKER], (
        "the board stands behind the edge, not behind the WAF alone, as on the VM range")
    assert run(ATTACKER, ["getent", "hosts", "board-db"]).exit_code != 0, "the database is named only on its own network"


def test_the_attacker_s_syn_scan_runs_with_the_capabilities_its_container_holds(facts):
    scan = run(ATTACKER, ["nmap", "-n", "-Pn", "-sS", "-p", "80", facts["waf"]], timeout=120)

    assert re.search(r"^80/tcp\s+open\b", scan.stdout, re.M), (
        f"a SYN scan needs raw sockets, which NET_RAW in the Kali container gives root: {scan.stdout[-400:]}")


def _scanned(targets: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    scan = run(ATTACKER, ["sh", "-c",
                          f"$(command -v sudo >/dev/null && echo sudo -n) nmap -n -Pn -sT --open -T4 "
                          f"--max-retries 1 --max-rtt-timeout 500ms --host-timeout 90s "
                          f"--min-hostgroup 256 --min-parallelism 256 "
                          f"-p {SERVICE_PORTS} {' '.join(targets)}"], timeout=900).stdout
    reports = SCANNED_HOST.split(scan)
    opened = {host: OPEN_PORT.findall(body) for host, body in zip(reports[1::2], reports[2::2])
              if OPEN_PORT.findall(body)}
    return opened, SKIPPED_HOST.findall(scan)


def test_the_attacker_reaches_no_service_on_the_range_host_the_platform_or_their_network(facts):
    targets = sorted({*facts["range_host"], *facts["platform"], *facts["host_networks"]})

    opened, skipped = _scanned(targets)

    assert not skipped, f"nmap gave up on {skipped} before scanning their ports, so they were never checked"
    assert facts["host_networks"] and not opened, (
        f"Kali reaches {opened} beyond its route to the sites; the range host, the platform and the "
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
        time.sleep(2)


def _session_to_plant_in(standing_stack) -> int:
    if standing_stack is not None:
        return standing_stack
    opened = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600)
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


def _closed(session: int):
    if STANDING.session == session:
        return STANDING.release()
    return requests.post(f"{PLATFORM_URL}/api/sessions/{session}/close/", json={}, timeout=120)


def test_a_link_planted_in_the_waf_neither_reaches_a_host_file_at_reset_nor_ships_another_log(standing_stack):
    token = uuid.uuid4().hex
    canary = json.dumps({"cr_probe": f"canary-{token}"})
    own = json.dumps({"cr_probe": f"own-{token}"})
    session = _session_to_plant_in(standing_stack)
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
        assert shipped_own and all(f"logs-{slot}-sensors-" in f"{index}-" for index in shipped_own), (
            f"a line the WAF wrote to its audit log did not reach slot {slot}'s index ({shipped_own}), "
            f"so the rest of this test would prove nothing: {wrote.output[-300:]}")

        planted = run(GATEWAY, ["sh", "-c",
                                f"cd {WAF_AUDIT}; ln -sf {CANARY} audit.log; ln -s {CANARY} planted; "
                                f"ln -s /var/log/cr/{other}/waf/audit.log other; ln -s /etc/passwd passwd; "
                                f"ls -la"], session=session)

        assert not _shipped_within(f"canary-{token}", PLANTED_WAIT), (
            f"a host file reached Elasticsearch after the WAF planted links to it: {planted.output[-600:]}")
    finally:
        closed = _closed(session)
    assert closed.status_code == 200, closed.text

    settled = _settled_after_close(slot)
    host = run(RANGE_HOST, ["sudo", "sh", "-c",
                            f"cat {CANARY}; echo --; find {host_log} -mindepth 1 -printf '%f %y %u\\n'; "
                            f"stat -c '%U %a' {host_log}; echo --; "
                            f"docker inspect -f '{{{{.State.StartedAt}}}}' s{slot}-waf; rm -f {CANARY}"],
               slot=int(slot))
    kept, listed, started = host.stdout.split("--\n")

    assert settled.get("phase") == "READY", f"slot {slot} did not settle after its reset: {settled}"
    assert started.strip() != waf_before, f"slot {slot}'s WAF was not recreated, so no reset ran"
    assert kept.strip() == canary, f"the reset wrote through a link the learner planted: {CANARY} is now {kept!r}"
    entries = listed.strip().splitlines()
    assert entries[0].startswith("audit.log f ") and entries[1:] == ["root 755"], (
        f"the WAF's log directory on the range host holds more than its own log file: {listed}")
    assert not _shipped(f"canary-{token}"), "a host file reached Elasticsearch after the reset"
