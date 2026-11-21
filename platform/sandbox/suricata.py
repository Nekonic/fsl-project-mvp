from __future__ import annotations

import base64
import binascii
import json
import re
import shlex
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from cr.config import SensorConfig
from cr.errors import EngineRefused, FieldError, Unavailable

RULE_PATH = "/var/lib/suricata/rules/local.rules"
MARKER_HEADER = "x-request-id"
CHECK_SCRATCH = "/tmp/cr-rule-check"
AT_LINE = re.compile(r"\bat line (\d+)\b")
ERROR_LINE = re.compile(r"(?:^|\s)(?:E:|<Error>|\[ERRCODE:|Error:)|error parsing signature", re.IGNORECASE)
RUN_ID = re.compile(r"[A-Za-z0-9_-]+")
OFFLINE_TIMEOUT = 300.0
LOGGING_OFF = re.compile(r"[(;]\s*config\s*:\s*logging\b", re.IGNORECASE)
READ_SNAPSHOT = 'exec 9>>"$1.lock"; flock -s 9; cat "$1/at" && cat "$1$2"'


class RuleApplyError(EngineRefused):
    code = "apply_refused"


class RuleSyntax(EngineRefused):
    code = "suricata_syntax"


class RulesUnreadable(Unavailable):
    code = "sensor_unavailable"


@dataclass(frozen=True)
class RuleError:
    line: int | None
    message: str

    def shown(self) -> dict:
        return {"line": self.line, "message": self.message}


@dataclass(frozen=True)
class Reloaded:
    text: str
    at: float


@dataclass(frozen=True)
class Capture:
    pid: int
    path: str


def current(sensor, config: SensorConfig) -> str:
    ran = sensor(["cat", config.rules])
    if not ran.ok:
        raise RulesUnreadable(f"could not read {config.rules}: {ran.output.strip()}")
    return ran.output


def parsed_errors(output: str) -> list[RuleError]:
    found = []
    for line in output.splitlines():
        if not ERROR_LINE.search(line):
            continue
        at = AT_LINE.search(line)
        found.append(RuleError(line=int(at.group(1)) if at else None, message=line.strip()))
    return found


def checked(text: str, sensor, config: SensorConfig) -> list[RuleError]:
    scratch = f"{CHECK_SCRATCH}-{uuid.uuid4().hex}"
    candidate = f"{scratch}/candidate.rules"
    script = (f"mkdir -p {scratch} && cat > {candidate} && "
              f"suricata -T -c {shlex.quote(config.settings_file)} -S {candidate} -l {scratch} 2>&1; "
              f"status=$?; rm -rf {scratch}; exit $status")
    ran = sensor(["sh", "-c", script], stdin=text)
    if ran.ok:
        return []
    return parsed_errors(ran.output) or [RuleError(line=None, message=ran.output.strip()[-500:])]


def rules_in(text: str) -> list[tuple[int, str]]:
    found, start, parts = [], 0, []
    for number, line in enumerate(text.splitlines(), start=1):
        if not parts:
            start = number
        kept = line.rstrip()
        if kept.endswith("\\") and (parts or not kept.lstrip().startswith("#")):
            parts.append(kept[:-1])
            continue
        found.append((start, "".join(parts) + line))
        parts = []
    if parts:
        found.append((start, "".join(parts)))
    return found


def refusals(text: str) -> list[RuleError]:
    return [RuleError(line=number, message="a rule may not turn off the sensor's logging (config: logging): "
                                           + rule.strip())
            for number, rule in rules_in(text)
            if not rule.lstrip().startswith("#") and LOGGING_OFF.search(rule)]


def reloaded(node, config: SensorConfig) -> Reloaded | None:
    ran = node(["sh", "-c", READ_SNAPSHOT, "sh", config.snapshot, config.rules])
    at, _, text = ran.output.partition("\n")
    if not ran.ok or not re.fullmatch(r"\d+(\.\d+)?", at.strip()):
        return None
    return Reloaded(text=text, at=float(at))


def refusal(errors: list[RuleError], sensor_name: str) -> RuleSyntax:
    return RuleSyntax(
        f"{sensor_name} refused the rules: " + "; ".join(error.message for error in errors),
        errors=tuple(FieldError(path="text", code=RuleSyntax.code, line=error.line,
                                params={"message": error.message, "sensor": sensor_name}) for error in errors),
    )


def apply(content: str, sensor, config: SensorConfig) -> None:
    errors = checked(content, sensor, config)
    if errors:
        raise refusal(errors, config.name)
    previous = current(sensor, config)
    _write(sensor, config.rules, content)
    ran = sensor(list(config.reload))
    if not _reloaded(ran):
        _write(sensor, config.rules, previous)
        raise RuleApplyError("reload failed, rolled back to the previous rule set: " + ran.output.strip())


def seed(content: str, sensor, config: SensorConfig) -> None:
    _write(sensor, config.rules, content)
    ran = sensor(list(config.reload))
    if not _reloaded(ran):
        raise RuleApplyError("the sensor did not load its starting rule set: " + ran.output.strip())


def scratch_of(config: SensorConfig, run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError(f"a run id is letters, digits, dashes and underscores, got {run_id!r}")
    scratch = PurePosixPath(config.scratch) / run_id
    live = PurePosixPath(config.live_logs)
    if scratch == live or live in scratch.parents or scratch in live.parents:
        raise ValueError(f"the scratch {scratch} must lie outside the live log directory {live}")
    return str(scratch)


def offline_argv(config: SensorConfig, scratch: str, case: str, pcap: str) -> list[str]:
    folder = str(PurePosixPath(pcap).parent)
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none",
            "-v", f"{config.settings_file}:{config.settings_file}:ro",
            "-v", f"{folder}:/pcaps:ro", "-v", f"{scratch}:/scratch",
            config.image, "-c", config.settings_file, "-k", "none",
            "-r", f"/pcaps/{PurePosixPath(pcap).name}", "-S", "/scratch/candidate.rules",
            "-l", f"/scratch/{case}"]


def offline_test(text: str, node, config: SensorConfig, pcaps: Mapping[str, str], run_id: str) -> dict[str, list[dict]]:
    scratch = scratch_of(config, run_id)
    for case in pcaps:
        if not RUN_ID.fullmatch(case):
            raise ValueError(f"a case id is letters, digits, dashes and underscores, got {case!r}")
    ready = node(["sh", "-c", f"rm -rf {scratch} && mkdir -p {scratch} && cat > {scratch}/candidate.rules"],
                 stdin=text)
    if not ready.ok:
        raise RulesUnreadable(f"{config.name} could not take the candidate rules: {ready.output.strip()[:300]}")
    found: dict[str, list[dict]] = {}
    try:
        for case, pcap in sorted(pcaps.items()):
            ran = node(["sh", "-c", f"mkdir -p {scratch}/{case} && {shlex.join(offline_argv(config, scratch, case, pcap))}"
                                    f" >/dev/null 2>&1; cat {scratch}/{case}/eve.json 2>/dev/null; true"],
                       timeout=OFFLINE_TIMEOUT)
            if not ran.ok:
                raise RulesUnreadable(f"{config.name} could not replay {case}: {ran.output.strip()[:300]}")
            found[case] = alerts_in(ran.output)
    finally:
        node(["rm", "-rf", scratch])
    return found


def alerts_in(eve: str) -> list[dict]:
    found = []
    for line in eve.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("event_type") != "alert":
            continue
        alert = record.get("alert") or {}
        found.append({"rule": str(alert.get("signature_id", "")), "signature": alert.get("signature", ""),
                      "marker": _marker(record.get("http") or {})})
    return found


def capture(node, config: SensorConfig, path: str, seconds: int) -> Capture:
    if not RUN_ID.fullmatch(PurePosixPath(path).stem) or not PurePosixPath(path).is_absolute():
        raise ValueError(f"a capture path is an absolute path to a plainly named file, got {path!r}")
    folder = str(PurePosixPath(path).parent)
    ran = node(["sh", "-c", f"mkdir -p {folder} && nohup timeout {int(seconds)} tcpdump -i "
                            f"{shlex.quote(config.interface)} -Z root -U -s 0 -w {path} >/dev/null 2>&1 & echo $!"])
    pid = ran.output.strip().splitlines()[-1] if ran.ok and ran.output.strip() else ""
    if not pid.isdigit():
        raise RulesUnreadable(f"{config.name} could not start a capture on {config.interface}: {ran.output.strip()[:300]}")
    return Capture(pid=int(pid), path=path)


def stop_capture(node, held: Capture) -> None:
    node(["sh", "-c", f"kill -INT {held.pid} 2>/dev/null; true"])


def captured(node, held: Capture) -> bytes:
    ran = node(["sh", "-c", f"base64 -w0 {shlex.quote(held.path)} && rm -f {shlex.quote(held.path)}"])
    if not ran.ok:
        raise RulesUnreadable(f"the capture {held.path} could not be read: {ran.output.strip()[:300]}")
    try:
        return base64.b64decode(ran.output.strip(), validate=True)
    except binascii.Error as broken:
        raise RulesUnreadable(f"the capture {held.path} came back garbled") from broken


def _marker(http: dict) -> str | None:
    for header in http.get("request_headers") or []:
        if str(header.get("name", "")).lower() == MARKER_HEADER:
            return header.get("value")
    return None


def _reloaded(ran) -> bool:
    return ran.ok and '"return":"OK"' in ran.output.replace(" ", "")


def _write(sensor, path: str, content: str) -> None:
    ran = sensor(["sh", "-c", f"mkdir -p {path.rpartition('/')[0]} && cat > {path}"], stdin=content)
    if not ran.ok:
        raise RuleApplyError(f"could not write {path}: {ran.output.strip()}")
