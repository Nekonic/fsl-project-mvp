from __future__ import annotations

from dataclasses import dataclass

RULE_PATH = "/var/lib/suricata/rules/local.rules"

class RuleApplyError(RuntimeError):
    pass

@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    output: str

def current(sensor) -> str:
    return sensor(["cat", RULE_PATH]).output

def validate(content: str, sensor) -> ValidationOutcome:
    ran = sensor(["suricata", "-T", "-S", "/dev/stdin"], stdin=content)
    return ValidationOutcome(ok=ran.ok, output=ran.output.strip())

def apply(content: str, sensor, reload_command) -> None:
    outcome = validate(content, sensor)
    if not outcome.ok:
        raise RuleApplyError(outcome.output)

    previous = current(sensor)
    _write(sensor, RULE_PATH, content)

    ran = sensor(list(reload_command))
    if not ran.ok:
        _write(sensor, RULE_PATH, previous)
        raise RuleApplyError(
            "reload failed, rolled back to the previous rule set: "
            + ran.output.strip()
        )

def _write(sensor, path: str, content: str) -> None:
    ran = sensor(["sh", "-c", "cat > " + path], stdin=content)
    if not ran.ok:
        raise RuleApplyError(f"could not write {path}: {ran.output.strip()}")
