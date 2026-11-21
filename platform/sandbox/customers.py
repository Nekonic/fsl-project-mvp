from __future__ import annotations

import ipaddress

from cr.config import BoxConfig
from sandbox.runner import RangeUnavailable

CUSTOMERS_ROLE = "customers"
ACCOUNT = "cr-users"
HOME = "/var/lib/cr-users"
PLAN = f"{HOME}/plan.json"
RECORDS = f"{HOME}/records.jsonl"
SERVICE = "cr-customers.service"
RECORDS_BEGIN = "cr.records="
RECORDS_END = "=cr.records"


class CustomersUnavailable(RangeUnavailable):
    pass


def customer_origins(described, config: BoxConfig) -> list[dict]:
    found = []
    for segment in described.segments:
        if not segment.origin:
            continue
        addresses = sorted({node.address for node in segment.nodes if node.name == config.customers},
                           key=ipaddress.ip_address)
        if addresses:
            found.append({"id": segment.id, "label": segment.origin, "target_url": config.target_url,
                          "addresses": addresses})
    return sorted(found, key=lambda origin: origin["id"])


def as_customer(argv: list[str]) -> list[str]:
    return ["sudo", "setpriv", f"--reuid={ACCOUNT}", f"--regid={ACCOUNT}", "--init-groups", *argv]


def _ran(box, script: str, what: str, stdin: str | None = None):
    ran = box(["sudo", "sh", "-c", script], stdin=stdin)
    if not ran.ok:
        raise CustomersUnavailable(f"the customers' box could not {what}: {ran.output.strip()[-300:]}")
    return ran


def run(box, plan: str) -> bool:
    ran = _ran(box, (
        f"set -e; umask 077; cat > {PLAN}.new; chown {ACCOUNT}: {PLAN}.new; mv {PLAN}.new {PLAN}; "
        f"if systemctl is-active --quiet {SERVICE}; then echo cr.customers=changed; exit 0; fi; "
        f": > {RECORDS}; chown {ACCOUNT}: {RECORDS}; systemctl start {SERVICE}; echo cr.customers=started"
    ), "start the customers", stdin=plan)
    return "cr.customers=started" in ran.output


def running(box) -> bool:
    return "cr.customers=yes" in _ran(
        box, f"if systemctl is-active --quiet {SERVICE}; then echo cr.customers=yes; fi",
        "say whether the customers run").output


def stop(box) -> None:
    _ran(box, f"rm -f {PLAN}; systemctl stop {SERVICE}", "stop the customers")


def records(box, offset: int, limit: int) -> str:
    said = _ran(box, (
        f"printf '{RECORDS_BEGIN}\\n'; tail -c +{int(offset) + 1} {RECORDS} 2>/dev/null "
        f"| head -c {int(limit)}; printf '\\n{RECORDS_END}\\n'"
    ), "hand over the customers' records").output
    begun = said.partition(f"{RECORDS_BEGIN}\n")[2]
    if f"\n{RECORDS_END}" not in begun:
        raise CustomersUnavailable(f"the customers' records ended early: {said.strip()[-200:]}")
    return begun.rpartition(f"\n{RECORDS_END}")[0]
