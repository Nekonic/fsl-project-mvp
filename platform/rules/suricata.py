from __future__ import annotations

from dataclasses import dataclass

RULE_PATH = "/var/lib/suricata/rules/local.rules"
CANDIDATE_PATH = "/var/lib/suricata/rules/candidate.rules"
RELOAD_SIGNAL = "USR2"

class RuleApplyError(RuntimeError):
    """The rules were not applied. The previous rule set is still live."""

@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    output: str

def current(sensor) -> str:
    return sensor(["cat", RULE_PATH]).output

def validate(content: str, sensor) -> ValidationOutcome:
    _write(sensor, CANDIDATE_PATH, content)
    ran = sensor(["suricata", "-T", "-S", CANDIDATE_PATH])
    return ValidationOutcome(ok=ran.ok, output=ran.output.strip())

def apply(content: str, sensor) -> None:
    outcome = validate(content, sensor)
    if not outcome.ok:
        raise RuleApplyError(outcome.output)

    previous = current(sensor)
    _write(sensor, RULE_PATH, content)

    ran = sensor(["kill", "-" + RELOAD_SIGNAL, "1"])
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
