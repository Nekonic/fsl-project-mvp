from __future__ import annotations

RULE_PATH = "/var/lib/suricata/rules/local.rules"

class RuleApplyError(RuntimeError):
    pass

class RulesUnreadable(RuntimeError):
    pass

def current(sensor) -> str:
    ran = sensor(["cat", RULE_PATH])
    if not ran.ok:
        raise RulesUnreadable(f"could not read {RULE_PATH}: {ran.output.strip()}")
    return ran.output

def validate(content: str, sensor):
    return sensor(["suricata", "-T", "-S", "/dev/stdin"], stdin=content)

def apply(content: str, sensor, reload_command) -> None:
    outcome = validate(content, sensor)
    if not outcome.ok:
        raise RuleApplyError(outcome.output.strip())

    previous = current(sensor)
    _write(sensor, RULE_PATH, content)

    ran = sensor(list(reload_command))
    if not ran.ok or '"return":"OK"' not in ran.output.replace(" ", ""):
        _write(sensor, RULE_PATH, previous)
        raise RuleApplyError(
            "reload failed, rolled back to the previous rule set: "
            + ran.output.strip()
        )

def _write(sensor, path: str, content: str) -> None:
    ran = sensor(["sh", "-c", "cat > " + path], stdin=content)
    if not ran.ok:
        raise RuleApplyError(f"could not write {path}: {ran.output.strip()}")
