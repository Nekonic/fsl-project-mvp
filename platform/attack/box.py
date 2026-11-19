from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from cr.config import BoxConfig
from cr.errors import NotFound
from range.runner import RangeUnavailable

ATTACKER_ROLE = "attacker"
RUNS = "/var/lib/cr-runs"
OUTPUT_LIMIT = 65536
RESOLUTION = timedelta(seconds=1)


class AttackerUnavailable(RangeUnavailable):
    code = "attacker_unavailable"


class UnknownOrigin(NotFound):
    code = "unknown_origin"


@dataclass(frozen=True)
class Command:
    at: datetime
    marker: str
    text: str


@dataclass(frozen=True)
class RunOutput:
    output: str
    offset: int
    done: bool
    exit_code: int | None


def origins(described, config: BoxConfig) -> list[dict]:
    box = config.proxy
    terminal = config.attacker

    standing = [
        (segment, {node.name: node.address for node in segment.nodes})
        for segment in described.segments
        if any(node.name == box for node in segment.nodes)
    ]
    if not standing:
        raise AttackerUnavailable(f"{box} is on no network at all")

    found = [
        {
            "id": segment.id,
            "network": segment.network,
            "label": segment.origin,
            "subnet": segment.subnet,
            "source_ip": addresses[box],
            "direct_ip": addresses.get(terminal, ""),
            "address": addresses.get(config.way_in) or segment.gateway,
            "target_url": config.target_url,
            "default": segment.id == config.default_origin,
        }
        for segment, addresses in standing
        if segment.origin and addresses.get(box)
    ]
    return sorted(found, key=lambda origin: origin["id"])


def find(described, origin_id: str | None, config: BoxConfig) -> dict:
    available = origins(described, config)
    if not origin_id:
        if not available:
            raise UnknownOrigin("the stack offers no origin to attack from")
        return next((o for o in available if o["default"]), available[0])
    for origin in available:
        if origin["id"] == origin_id:
            return origin
    raise UnknownOrigin(
        f"no origin {origin_id!r}; the stack offers "
        f"{[o['id'] for o in available]}"
    )


def kali_address(adapter) -> str:
    return adapter.address(ATTACKER_ROLE)


def launch_with(launcher, config: BoxConfig):
    def launch(argv: list[str], timeout: float = 600.0):
        return launcher(config.tool_image, argv, timeout=timeout)

    return launch


def commands(box, config: BoxConfig) -> list[Command]:
    ran = box(["cat", config.command_log])
    if not ran.ok:
        if "No such file" in ran.output:
            return []
        raise AttackerUnavailable(f"could not read {config.command_log}: {ran.output.strip()[:200]}")
    return [record for line in ran.output.splitlines() if (record := _command(line)) is not None]


def within(typed: list[Command], start: datetime, end: datetime | None) -> list[Command]:
    opened = start.replace(microsecond=0)
    closed = None if end is None else end.replace(microsecond=0) + RESOLUTION
    return [command for command in typed if command.at >= opened and (closed is None or command.at < closed)]


def _command(line: str) -> Command | None:
    stamp, _, rest = line.partition("\t")
    marker, tab, text = rest.partition("\t")
    if not tab or not text:
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return Command(at=at, marker=marker, text=text)


def _run_dir(run_id: int) -> str:
    return f"{RUNS}/{int(run_id)}"


def start_run(box, run_id: int, argv: list[str]) -> None:
    folder = _run_dir(run_id)
    _ran(box, (
        f"set -e; rm -rf {folder}; mkdir -p {folder}; cd {folder}; "
        f"setsid nohup sh -c '\"$@\" >{folder}/output 2>&1; echo $? > {folder}/exit' sh {shlex.join(argv)} "
        f"</dev/null >/dev/null 2>&1 & echo $! > {folder}/pid"
    ), f"start run {run_id}")


def run_output(box, run_id: int, offset: int = 0, limit: int = OUTPUT_LIMIT) -> RunOutput:
    folder = _run_dir(run_id)
    said = _ran(box, (
        f"[ -d {folder} ] || {{ echo cr.run=missing; exit 0; }}; "
        f"cat {folder}/exit 2>/dev/null | sed 's/^/cr.exit=/'; printf 'cr.output=\\n'; "
        f"tail -c +{int(offset) + 1} {folder}/output 2>/dev/null | head -c {int(limit)}"
    ), f"hand over run {run_id}").output
    if said.startswith("cr.run=missing"):
        raise NotFound(f"no run {run_id} on the box", code="unknown_run")
    head, _, output = said.partition("cr.output=\n")
    exit_line = next((line for line in head.splitlines() if line.startswith("cr.exit=")), "")
    code = exit_line.removeprefix("cr.exit=").strip()
    return RunOutput(output=output, offset=int(offset) + len(output.encode()), done=bool(exit_line),
                     exit_code=int(code) if code.lstrip("-").isdigit() else None)


def stop_run(box, run_id: int) -> None:
    folder = _run_dir(run_id)
    _ran(box, (
        f"[ -f {folder}/pid ] || exit 0; pid=$(cat {folder}/pid); "
        f"kill -TERM -- -$pid 2>/dev/null || kill -TERM $pid 2>/dev/null || true; "
        f"[ -f {folder}/exit ] || echo 143 > {folder}/exit"
    ), f"stop run {run_id}")


def wear_origin(chosen: dict, box) -> None:
    ran = box(["sudo", "/usr/local/sbin/set-origin", chosen["source_ip"]])
    if not ran.ok:
        raise AttackerUnavailable(
            f"the box could not wear {chosen['source_ip']}: {ran.output.strip()[:200]}"
        )

def set_label(case_id: str | None, proxy, config: BoxConfig) -> None:
    _write(proxy, config.label_file, case_id)

SQLMAP_HOMES = ("/root", "/home/*")
SQLMAP_RUNS = "/tmp/sqlmap-runs"
SQLMAP_OUTPUTS = (".local/share/sqlmap/output", ".sqlmap/output")
SQLMAP_INJECTABLE = re.compile(r"^Parameter: ", re.M)

def sqlmap_found(box, host: str) -> bool | None:
    logs = " ".join(f"{home}/{output}/{shlex.quote(host)}/log" for home in SQLMAP_HOMES for output in SQLMAP_OUTPUTS)
    ran = box(["sh", "-c", f"cat {logs} 2>/dev/null; true"])
    return bool(SQLMAP_INJECTABLE.search(ran.output)) if ran.ok else None

NO_TERMINAL = "?"
PROGRAM_WORDS = 3

def typed_tool_running(box, tool: str) -> bool | None:
    ran = box(["ps", "-eo", "tty=,args="])
    if not ran.ok:
        return None
    return any(_runs_on_a_terminal(line.split(), tool) for line in ran.output.splitlines())

def _runs_on_a_terminal(fields: list[str], tool: str) -> bool:
    return (len(fields) > 1 and fields[0] != NO_TERMINAL
            and any(word.rpartition("/")[2] in (tool, f"{tool}.py") for word in fields[1:1 + PROGRAM_WORDS]))

def _write(proxy, where: str, value: str | None) -> None:
    ran = proxy(["sh", "-c", f"cat > {where}"], stdin=value or "")
    if not ran.ok:
        raise AttackerUnavailable(
            f"the proxy could not write {where}: {ran.output.strip()[:200]}"
        )

CUSTOMERS_ACCOUNT = "cr-users"
CUSTOMERS_HOME = "/var/lib/cr-users"
CUSTOMERS_PROGRAM = f"{CUSTOMERS_HOME}/users.py"
CUSTOMERS_PLAN = f"{CUSTOMERS_HOME}/plan.json"
CUSTOMERS_RECORDS = f"{CUSTOMERS_HOME}/records.jsonl"
CUSTOMERS_PID = f"{CUSTOMERS_HOME}/pid"
CUSTOMERS_LOG = f"{CUSTOMERS_HOME}/log"
CUSTOMERS_RUNNING = f'[ -f {CUSTOMERS_PID} ] && kill -0 "$(cat {CUSTOMERS_PID})" 2>/dev/null'
CUSTOMERS_STOP_WAIT = 50
ROUTE_SOURCE = re.compile(r"\bsrc (\S+)")
RECORDS_BEGIN = "cr.records="
RECORDS_END = "=cr.records"

def _as_root(script: str) -> list[str]:
    return ["sudo", "sh", "-c", script]

def _ran(box, script: str, what: str, stdin: str | None = None, timeout: float = 60.0):
    ran = box(_as_root(script), stdin=stdin, timeout=timeout)
    if not ran.ok:
        raise AttackerUnavailable(f"the box could not {what}: {ran.output.strip()[-300:]}")
    return ran

def unbound_source(box, config: BoxConfig) -> str:
    host = shlex.quote(urlsplit(config.target_url).hostname or "")
    ran = _ran(box, f"ip -o route get \"$(getent ahostsv4 {host} | awk 'NR==1{{print $1}}')\"",
               "say which address it sends from")
    found = ROUTE_SOURCE.search(ran.output)
    if found is None:
        raise AttackerUnavailable(f"the box named no source address for {host}: {ran.output.strip()[:200]}")
    return found[1]

def customer_origins(described, config: BoxConfig, unbound: str = "") -> list[dict]:
    attackers = origins(described, config)
    taken = {origin["source_ip"] for origin in attackers} | {unbound}
    box = config.proxy
    by_id = {segment.id: segment for segment in described.segments}
    found = []
    for origin in attackers:
        if origin["id"] == config.default_origin:
            continue
        addresses = sorted(
            {node.address for node in by_id[origin["id"]].nodes if node.name == box} - taken,
            key=ipaddress.ip_address,
        )
        if not addresses:
            continue
        found.append({"id": origin["id"], "label": origin["label"],
                      "target_url": origin["target_url"], "addresses": addresses})
    return found

def place_customers(box, program: str) -> None:
    account = (
        _customers_account()
        + f"install -d -m 0755 -o {CUSTOMERS_ACCOUNT} -g {CUSTOMERS_ACCOUNT} {CUSTOMERS_HOME}; "
    )
    _ran(box, "set -e; " + account + f"cat > {CUSTOMERS_PROGRAM}.new; mv {CUSTOMERS_PROGRAM}.new {CUSTOMERS_PROGRAM}",
         "take the customers' program", stdin=program)

SITE_BRIDGE = (
    "import socket, sys, threading\n"
    "line = socket.create_connection((sys.argv[2], int(sys.argv[3])), 10, (sys.argv[1], 0))\n"
    "def up():\n"
    "    while chunk := sys.stdin.buffer.read1(65536):\n"
    "        line.sendall(chunk)\n"
    "    line.shutdown(socket.SHUT_WR)\n"
    "threading.Thread(target=up, daemon=True).start()\n"
    "while chunk := line.recv(65536):\n"
    "    sys.stdout.buffer.write(chunk)\n"
    "    sys.stdout.buffer.flush()\n"
)

def _customers_account() -> str:
    return (
        f"id -u {CUSTOMERS_ACCOUNT} >/dev/null 2>&1 || useradd --system --no-create-home "
        f"--shell /usr/sbin/nologin {CUSTOMERS_ACCOUNT}; "
        f"iptables -t nat -C POSTROUTING -m owner --uid-owner {CUSTOMERS_ACCOUNT} -j RETURN 2>/dev/null "
        f"|| iptables -t nat -I POSTROUTING 1 -m owner --uid-owner {CUSTOMERS_ACCOUNT} -j RETURN; "
    )

def as_customer(source: str, address: str, port: int) -> list[str]:
    bridge = shlex.join(["python3", "-c", SITE_BRIDGE, source, address, str(port)])
    return ["sudo", "sh", "-c", _customers_account()
            + f"exec setpriv --reuid={CUSTOMERS_ACCOUNT} --regid={CUSTOMERS_ACCOUNT} --init-groups {bridge}"]

def as_customer_command(argv: list[str]) -> list[str]:
    return ["sudo", "sh", "-c", _customers_account()
            + f"exec setpriv --reuid={CUSTOMERS_ACCOUNT} --regid={CUSTOMERS_ACCOUNT} --init-groups "
            + shlex.join(argv)]

def run_customers(box, plan: str) -> bool:
    owner = f"chown {CUSTOMERS_ACCOUNT}: {CUSTOMERS_PLAN}.new; "
    user = f"setpriv --reuid={CUSTOMERS_ACCOUNT} --regid={CUSTOMERS_ACCOUNT} --init-groups "
    ran = _ran(box, (
        f"set -e; umask 077; cat > {CUSTOMERS_PLAN}.new; {owner}mv {CUSTOMERS_PLAN}.new {CUSTOMERS_PLAN}; "
        f"if {CUSTOMERS_RUNNING}; then echo cr.customers=changed; exit 0; fi; "
        f"cd {CUSTOMERS_HOME}; umask 022; "
        f"setsid {user}python3 {CUSTOMERS_PROGRAM} {CUSTOMERS_PLAN} {CUSTOMERS_RECORDS} "
        f"</dev/null >>{CUSTOMERS_LOG} 2>&1 & echo $! > {CUSTOMERS_PID}; echo cr.customers=started"
    ), "start the customers", stdin=plan)
    return "cr.customers=started" in ran.output

def customers_running(box) -> bool:
    return "cr.customers=yes" in _ran(
        box, f"if {CUSTOMERS_RUNNING}; then echo cr.customers=yes; fi", "say whether the customers run").output

def stop_customers(box) -> None:
    _ran(box, (
        f"rm -f {CUSTOMERS_PLAN}; "
        f"if [ -f {CUSTOMERS_PID} ]; then kill \"$(cat {CUSTOMERS_PID})\" 2>/dev/null || true; "
        f"for _ in $(seq {CUSTOMERS_STOP_WAIT}); do {CUSTOMERS_RUNNING} || break; sleep 0.2; done; "
        f"if {CUSTOMERS_RUNNING}; then kill -9 \"$(cat {CUSTOMERS_PID})\"; fi; rm -f {CUSTOMERS_PID}; fi"
    ), "stop the customers")

def customer_records(box, offset: int, limit: int) -> str:
    said = _ran(box, (
        f"printf '{RECORDS_BEGIN}\\n'; tail -c +{int(offset) + 1} {CUSTOMERS_RECORDS} 2>/dev/null "
        f"| head -c {int(limit)}; printf '\\n{RECORDS_END}\\n'"
    ), "hand over the customers' records").output
    begun = said.partition(f"{RECORDS_BEGIN}\n")[2]
    if f"\n{RECORDS_END}" not in begun:
        raise AttackerUnavailable(f"the box's records ended early: {said.strip()[-200:]}")
    return begun.rpartition(f"\n{RECORDS_END}")[0]

LEARNER_ACCOUNT = "kali"
