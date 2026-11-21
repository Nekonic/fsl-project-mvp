import ipaddress
import re
import shlex
import time
import uuid

import pytest

import plays
from conftest import STANDING
from opening import READY
from range import ATTACKER, BOARD, LOG_SERVER, log_collector, platform_addresses, run, run_side_by_side

GATEWAY = "gateway"
PROBERS = (ATTACKER, GATEWAY, BOARD)
ROUTER = "121.134.88.42"
PUBLIC_NAME = "board.com"
DEFAULT_DEV = re.compile(r"^default via \S+ dev (\S+)", re.M)
ADDRESS = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\S+)", re.M)
UPSTREAM = re.compile(r"^(\S+)\s+(board|corp-wp)$", re.M)
PAST_THE_WAF = {"board": 8000, "corp-wp": 80}
NAMED_ONLY_INSIDE = ("board", "corp-wp", "board-db", "corp-db")
SERVICE_PORTS = "22,80,443,514,3306,5140,5601,8000,8080,9200"
OPEN_PORT = re.compile(r"^(\d+)/tcp\s+open\b", re.M)
SCANNED_HOST = re.compile(r"^Nmap scan report for (\S+)", re.M)
SKIPPED_HOST = re.compile(r"^Skipping host (\S+) due to host timeout", re.M)
HOP = re.compile(r"^\s*(\d+)\s+(\S+)", re.M)
CANARY = "/var/log/cr-isolation-canary.log"
BOOT_ID = "/proc/sys/kernel/random/boot_id"
SPOOFED = "cr-spoof0"
SPOOFED_MAC = "02:00:5e:10:00:01"
SETTLE_WAIT = 1800


def connect(address: str, port: int) -> list[str]:
    return ["timeout", "5", "bash", "-c", f"exec 3<>/dev/tcp/{address}/{port}"]


def addresses_of(listed: str) -> list[ipaddress.IPv4Interface]:
    return [ipaddress.ip_interface(address) for _, address in ADDRESS.findall(listed)
            if not ipaddress.ip_interface(address).ip.is_loopback]


def waf_side(allocation: int | None = None) -> dict:
    return run_side_by_side(GATEWAY, {
        "addresses": ["ip", "-o", "-4", "addr", "show"],
        "route": ["ip", "-4", "route", "show", "default"],
        "upstreams": ["getent", "hosts", *PAST_THE_WAF],
    }, allocation=allocation)


def front_of(waf: dict) -> str:
    default_dev = DEFAULT_DEV.search(waf["route"].stdout).group(1)
    return next(str(ipaddress.ip_interface(address).ip) for dev, address in ADDRESS.findall(waf["addresses"].stdout)
                if dev == default_dev)


def slot_of(allocation: int | None = None) -> str:
    return run(LOG_SERVER, ["sh", "-c", ". /etc/slot.env && echo $SLOT"], allocation=allocation).stdout.strip()


@pytest.fixture(scope="module")
def facts():
    waf = waf_side()
    collector = log_collector()
    own = {role: addresses_of(run(role, ["ip", "-o", "-4", "addr", "show"]).stdout) for role in (ATTACKER, GATEWAY)}
    control = next(one.network for one in own[ATTACKER] if ipaddress.ip_address(collector) in one.network)
    public = run(ATTACKER, ["getent", "ahostsv4", PUBLIC_NAME]).stdout.split()
    return {
        "waf": front_of(waf),
        "public": public[0] if public else "",
        "upstreams": {name: address for address, name in UPSTREAM.findall(waf["upstreams"].stdout)},
        "platform": platform_addresses(collector),
        "control": control,
        "own": {role: sorted(str(one.ip) for one in found) for role, found in own.items()},
    }


def probes(facts) -> dict[str, list[tuple[str, int]]]:
    return {
        "platform": [(address, port) for address in facts["platform"] for port in (8000, 22)],
        "outside": [("1.1.1.1", 443), ("169.254.169.254", 80)],
        "way in": [(facts["public"], 80)],
        "behind the router": [(facts["waf"], 80)],
        "past the waf": [(facts["upstreams"][name], port) for name, port in sorted(PAST_THE_WAF.items())],
    }


ATTACKER_ONLY = ("way in", "behind the router", "past the waf")


@pytest.fixture(scope="module")
def reached(facts):
    found = {}
    for role in PROBERS:
        targets = sorted({target for what, listed in probes(facts).items() for target in listed
                          if what not in ATTACKER_ONLY or role == ATTACKER})
        ran = run_side_by_side(role, {target: connect(*target) for target in targets}, timeout=120)
        found[role] = {target for target, result in ran.items() if result.ok}
    return found


def reaching(reached, facts, role: str, what: str) -> list[str]:
    return [f"{address}:{port}" for address, port in probes(facts)[what] if (address, port) in reached[role]]


@pytest.mark.parametrize("role", PROBERS)
def test_no_learner_shell_reaches_the_platform(reached, facts, role):
    found = reaching(reached, facts, role, "platform")

    assert facts["platform"] and not found, f"{role} reaches the platform at {found}"


@pytest.mark.parametrize("role", PROBERS)
def test_no_learner_shell_reaches_the_internet_or_the_cloud_s_metadata(reached, facts, role):
    found = reaching(reached, facts, role, "outside")

    assert not found, f"{role} leaves the slot for {found}"


def test_the_attacker_reaches_the_sites_only_through_the_waf(reached, facts):
    assert sorted(facts["upstreams"]) == sorted(PAST_THE_WAF), f"the WAF names no upstream for {facts['upstreams']}"
    assert facts["public"] == ROUTER and (facts["public"], 80) in reached[ATTACKER], (
        f"the attack has no way in at all: {PUBLIC_NAME} names {facts['public']!r} on Kali")
    behind = reaching(reached, facts, ATTACKER, "behind the router")
    assert not behind, (
        f"Kali opens {behind}, the WAF's private address behind the router; an edge router lets in from the "
        f"Internet only the port it forwards on its public address and the replies to connections from inside")
    past = reaching(reached, facts, ATTACKER, "past the waf")
    assert not past, f"Kali reaches {past} through the edge without passing the WAF, so the WAF's rules decide nothing"
    named = run_side_by_side(ATTACKER, {name: ["getent", "hosts", name] for name in NAMED_ONLY_INSIDE})
    assert not [name for name, found in named.items() if found.exit_code == 0], (
        "a target behind the WAF is named on Kali, so a URL by its name skips board.com and the WAF")


def test_the_attacker_pings_and_traces_the_router_s_public_address():
    pinged = run(ATTACKER, ["ping", "-n", "-c", "3", "-W", "2", ROUTER], timeout=60)
    traced = run(ATTACKER, ["traceroute", "-n", "-w", "2", "-q", "1", "-m", "5", ROUTER], timeout=60)

    assert pinged.ok and " 0% packet loss" in pinged.stdout, pinged.output[-400:]
    hops = HOP.findall(traced.stdout)
    assert traced.ok and hops and hops[-1][1] == ROUTER, (
        f"the router answers traceroute's last probe port unreachable, so the trace ends on it: {traced.output[-400:]}")


def test_the_attacker_s_syn_scan_runs_as_root_and_the_waf_s_private_address_is_filtered(facts):
    public = run(ATTACKER, ["nmap", "-n", "-Pn", "-sS", "-p", "80", facts["public"]], timeout=120)
    behind = run(ATTACKER, ["nmap", "-n", "-Pn", "-sS", "-p", "80", facts["waf"]], timeout=120)

    assert re.search(r"^80/tcp\s+open\b", public.stdout, re.M), (
        f"a SYN scan needs raw sockets, which root on Kali has: {public.stdout[-400:]}")
    assert re.search(r"^80/tcp\s+filtered\b", behind.stdout, re.M), (
        f"the edge answers a SYN scan of the WAF's private address; it drops it: {behind.stdout[-400:]}")


def _scanned(role: str, targets: list[str], excluded: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    scan = run(role, ["sh", "-c",
                      f"nmap -n -Pn -sT --open -T4 --max-retries 1 --max-rtt-timeout 500ms --host-timeout 90s "
                      f"--min-hostgroup 256 --min-parallelism 256 -p {SERVICE_PORTS} "
                      f"--exclude {','.join(excluded)} {' '.join(targets)}"], timeout=900).stdout
    reports = SCANNED_HOST.split(scan)
    opened = {host: OPEN_PORT.findall(body) for host, body in zip(reports[1::2], reports[2::2])
              if OPEN_PORT.findall(body)}
    return opened, SKIPPED_HOST.findall(scan)


def test_the_attacker_reaches_no_service_on_the_control_network_of_its_own_or_any_other_slot_or_the_platform(facts):
    opened, skipped = _scanned(ATTACKER, [str(facts["control"]), *facts["platform"]], facts["own"][ATTACKER])

    assert not skipped, f"nmap gave up on {skipped} before scanning their ports, so they were never checked"
    assert not opened, (
        f"Kali reaches {opened} on {facts['control']}, where every slot VM and the platform have their control "
        f"port; those take ssh from the platform only")


def test_the_attacker_cannot_send_from_a_mac_address_neutron_did_not_give_its_port(facts):
    internet = run(ATTACKER, ["sh", "-c", f"ip -o -4 route get {ROUTER} | sed -n 's/.* dev \\([^ ]*\\).*/\\1/p'"])
    dev = internet.stdout.strip()
    source = next(address for address in facts["own"][ATTACKER]
                  if not ipaddress.ip_address(address) in facts["control"])
    spoofed = (f"ip link add {SPOOFED} link {dev} address {SPOOFED_MAC} type macvlan mode bridge && "
               f"ip link set {SPOOFED} up && ping -n -c 3 -W 2 -I {SPOOFED} {ROUTER}; "
               f"code=$?; ip link del {SPOOFED}; exit $code")
    try:
        own = run(ATTACKER, ["ping", "-n", "-c", "1", "-W", "2", "-I", source, ROUTER], timeout=60)
        other = run(ATTACKER, ["sh", "-c", spoofed], timeout=60)
    finally:
        run(ATTACKER, ["sh", "-c", f"ip link del {SPOOFED} 2>/dev/null; true"])

    assert dev and own.ok, f"Kali does not reach the router from its own port, so this proves nothing: {own.output}"
    assert not other.ok, (
        f"a frame from {SPOOFED_MAC} reached the router; port security lets Kali's port send only from the MAC "
        f"Neutron gave it, whatever source IP the allowed address pair takes: {other.output[-400:]}")


def _settled_after_close(slot: str) -> dict:
    deadline = time.monotonic() + SETTLE_WAIT
    while True:
        mine = next((each for each in plays.slots() if str(each.get("slot")) == slot), {})
        settled = mine.get("allocation") is None and (mine.get("refill") or {}).get("state") == READY
        if settled or time.monotonic() > deadline:
            return mine
        time.sleep(5)


def _played_to_plant_in(standing_stack) -> plays.Played:
    if standing_stack is not None:
        return STANDING.played
    return plays.play("board")


def _closed(played: plays.Played) -> plays.Answer:
    if STANDING.played is played:
        STANDING.release()
        return plays.Answer(200, {"closed": None})
    return plays.close(played)


def test_a_refill_gives_the_next_allocation_a_new_waf_vm_with_nothing_the_last_learner_left(standing_stack):
    token = uuid.uuid4().hex
    played = _played_to_plant_in(standing_stack)
    try:
        slot = slot_of(played.allocation)
        planted = run(GATEWAY, ["sh", "-c", f"printf '%s\\n' {shlex.quote(token)} > {CANARY} && cat {BOOT_ID}"],
                      allocation=played.allocation)
        assert planted.ok, planted.output
        booted = planted.stdout.strip()
    finally:
        closed = _closed(played)
    assert closed.ok, closed.text

    settled = _settled_after_close(slot)
    after = run(GATEWAY, ["sh", "-c", f"cat {BOOT_ID}; cat {CANARY} 2>/dev/null; true"], slot=int(slot))

    assert (settled.get("refill") or {}).get("state") == READY, (
        f"slot {slot} did not settle after its refill: {settled}")
    assert booted not in after.stdout, f"slot {slot}'s WAF is the VM the last allocation had, so no refill ran"
    assert token not in after.stdout, f"the file the last learner wrote on the WAF is still there: {after.stdout}"
