from __future__ import annotations

import ipaddress
import re
import shlex
from urllib.parse import urlsplit

from django.conf import settings

from range.ports import RangeUnavailable

class AttackerUnavailable(RangeUnavailable):
    pass

class UnknownOrigin(ValueError):
    pass

def _target_url(address: str) -> str:
    parts = urlsplit(settings.TARGET_URL)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{address}{port}"

def _way_in() -> str:
    roles = settings.RANGE.roles
    return roles.get("edge") or roles["gateway"]

def origins(described) -> list[dict]:
    box = settings.ATTACKER_SOURCE_CONTAINER
    terminal = settings.ATTACKER_CONTAINER
    way_in = _way_in()
    by_name = "edge" in settings.RANGE.roles

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
            "address": addresses.get(way_in) or segment.gateway,
            "target_url": settings.ATTACKER_TARGET_URL if by_name
            else _target_url(addresses[way_in]),
            "default": segment.id == settings.RANGE.default_origin,
        }
        for segment, addresses in standing
        if segment.origin and addresses.get(box)
        and (by_name or addresses.get(way_in))
    ]
    return sorted(found, key=lambda origin: origin["id"])

def find(described, origin_id: str | None) -> dict:
    available = origins(described)
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

def set_origin(address: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_ORIGIN_FILE, address)

def wear_origin(chosen: dict, box) -> None:
    if settings.ATTACKER_ORIGIN_MODE == "snat":
        ran = box(["sudo", "/usr/local/sbin/set-origin", chosen["source_ip"]])
        if not ran.ok:
            raise AttackerUnavailable(
                f"the box could not wear {chosen['source_ip']}: {ran.output.strip()[:200]}"
            )
        return
    set_origin(chosen["address"], box)

def set_label(case_id: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_LABEL_FILE, case_id)

SQLMAP_HOMES = ("/root", "/home/*")
SQLMAP_OUTPUTS = (".local/share/sqlmap/output", ".sqlmap/output")
SQLMAP_INJECTABLE = re.compile(r"^Parameter: ", re.M)

def sqlmap_found(box, host: str) -> bool | None:
    logs = " ".join(f"{home}/{output}/{shlex.quote(host)}/log" for home in SQLMAP_HOMES for output in SQLMAP_OUTPUTS)
    ran = box(["sh", "-c", f"cat {logs} 2>/dev/null; true"])
    return bool(SQLMAP_INJECTABLE.search(ran.output)) if ran.ok else None

def _write(proxy, where: str, value: str | None) -> None:
    ran = proxy(["sh", "-c", f"cat > {where}"], stdin=value or "")
    if not ran.ok:
        raise AttackerUnavailable(
            f"the proxy could not write {where}: {ran.output.strip()[:200]}"
        )

CUSTOMERS_ACCOUNT = "fsl-users"
CUSTOMERS_HOME = "/var/lib/fsl-users"
CUSTOMERS_PROGRAM = f"{CUSTOMERS_HOME}/users.py"
CUSTOMERS_PLAN = f"{CUSTOMERS_HOME}/plan.json"
CUSTOMERS_RECORDS = f"{CUSTOMERS_HOME}/records.jsonl"
CUSTOMERS_PID = f"{CUSTOMERS_HOME}/pid"
CUSTOMERS_LOG = f"{CUSTOMERS_HOME}/log"
CUSTOMERS_RUNNING = f'[ -f {CUSTOMERS_PID} ] && kill -0 "$(cat {CUSTOMERS_PID})" 2>/dev/null'
CUSTOMERS_STOP_WAIT = 50
ROUTE_SOURCE = re.compile(r"\bsrc (\S+)")
RECORDS_BEGIN = "fsl.records="
RECORDS_END = "=fsl.records"

def _snat() -> bool:
    return settings.ATTACKER_ORIGIN_MODE == "snat"

def _as_root(script: str) -> list[str]:
    return ["sudo", "sh", "-c", script] if _snat() else ["sh", "-c", script]

def _ran(box, script: str, what: str, stdin: str | None = None, timeout: float = 60.0):
    ran = box(_as_root(script), stdin=stdin, timeout=timeout)
    if not ran.ok:
        raise AttackerUnavailable(f"the box could not {what}: {ran.output.strip()[-300:]}")
    return ran

def unbound_source(box) -> str:
    host = shlex.quote(urlsplit(settings.ATTACKER_TARGET_URL).hostname or "")
    ran = _ran(box, f"ip -o route get \"$(getent ahostsv4 {host} | awk 'NR==1{{print $1}}')\"",
               "say which address it sends from")
    found = ROUTE_SOURCE.search(ran.output)
    if found is None:
        raise AttackerUnavailable(f"the box named no source address for {host}: {ran.output.strip()[:200]}")
    return found[1]

def customer_origins(described, unbound: str = "") -> list[dict]:
    attackers = origins(described)
    taken = {origin["source_ip"] for origin in attackers} | {unbound}
    box = settings.ATTACKER_SOURCE_CONTAINER
    by_id = {segment.id: segment for segment in described.segments}
    found = []
    for origin in attackers:
        if origin["id"] == settings.RANGE.default_origin:
            continue
        addresses = sorted(
            {node.address for node in by_id[origin["id"]].nodes if node.name == box} - taken,
            key=ipaddress.ip_address,
        ) if _snat() else []
        if _snat() and not addresses:
            continue
        found.append({"id": origin["id"], "label": origin["label"],
                      "target_url": origin["target_url"], "addresses": addresses})
    return found

def place_customers(box, program: str) -> None:
    account = (
        _customers_account()
        + f"install -d -m 0755 -o {CUSTOMERS_ACCOUNT} -g {CUSTOMERS_ACCOUNT} {CUSTOMERS_HOME}; "
    ) if _snat() else f"install -d -m 0755 {CUSTOMERS_HOME}; "
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
    if not _snat():
        return ["sh", "-c", f"exec {bridge}"]
    return ["sudo", "sh", "-c", _customers_account()
            + f"exec setpriv --reuid={CUSTOMERS_ACCOUNT} --regid={CUSTOMERS_ACCOUNT} --init-groups {bridge}"]

def run_customers(box, plan: str) -> bool:
    owner = f"chown {CUSTOMERS_ACCOUNT}: {CUSTOMERS_PLAN}.new; " if _snat() else ""
    user = (f"setpriv --reuid={CUSTOMERS_ACCOUNT} --regid={CUSTOMERS_ACCOUNT} --init-groups "
            if _snat() else "")
    ran = _ran(box, (
        f"set -e; umask 077; cat > {CUSTOMERS_PLAN}.new; {owner}mv {CUSTOMERS_PLAN}.new {CUSTOMERS_PLAN}; "
        f"if {CUSTOMERS_RUNNING}; then echo fsl.customers=changed; exit 0; fi; "
        f"cd {CUSTOMERS_HOME}; umask 022; "
        f"setsid {user}python3 {CUSTOMERS_PROGRAM} {CUSTOMERS_PLAN} {CUSTOMERS_RECORDS} "
        f"</dev/null >>{CUSTOMERS_LOG} 2>&1 & echo $! > {CUSTOMERS_PID}; echo fsl.customers=started"
    ), "start the customers", stdin=plan)
    return "fsl.customers=started" in ran.output

def customers_running(box) -> bool:
    return "fsl.customers=yes" in _ran(
        box, f"if {CUSTOMERS_RUNNING}; then echo fsl.customers=yes; fi", "say whether the customers run").output

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
