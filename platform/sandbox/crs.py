from __future__ import annotations

import json
import re
import shlex
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from cr.config import WafConfig
from cr.errors import EngineRefused, FieldError, Unavailable


def workers_of(pid: str) -> str:
    return ('m=$(cat ' + pid + '); for d in /proc/[0-9]*; do '
            '[ "$(cut -d" " -f4 $d/stat 2>/dev/null)" = "$m" ] && echo ${d#/proc/}; done; true')

SETTLE_POLLS = 50
FIRST_ID = 10000
MOST_EXCLUSIONS = 20
TARGET = re.compile(r"(ARGS|ARGS_GET|ARGS_POST|ARGS_NAMES|REQUEST_COOKIES|REQUEST_HEADERS)(:[\w-]+)?|REQUEST_URI_RAW|REQUEST_BODY", re.ASCII)
PATH = re.compile(r"/[\w./-]*", re.ASCII)
TAG = re.compile(r"[A-Za-z][A-Za-z_-]*", re.ASCII)
THRESHOLDS = ("inbound", "outbound")
HIGHEST_THRESHOLD = 100000

LEVEL = re.compile(r"tx\.blocking_paranoia_level=([1-4])\b")
REMOVED = re.compile(r"ctl:ruleRemove(?:TargetById=(\d+);([\w:-]+)|ById=(\d+)|TargetByTag=([A-Za-z][A-Za-z_-]*);([\w:-]+))")
BEGINS = re.compile(r'"@beginsWith (/[\w./-]*)"')
THRESHOLD = re.compile(r"tx\.(inbound|outbound)_anomaly_score_threshold=(\d+)")

class TuningRefused(EngineRefused, ValueError):
    code = "crs_refused"

class WafUnreadable(Unavailable):
    code = "waf_unavailable"

def checked(tuning) -> dict:
    if not isinstance(tuning, dict):
        raise TuningRefused("the tuning is an object with paranoia and exclusions", path="posture")
    paranoia = tuning.get("paranoia")
    if type(paranoia) is not int or not 1 <= paranoia <= 4:
        raise TuningRefused(f'"paranoia" must be a paranoia level from 1 to 4, got {paranoia!r}', path="paranoia")
    exclusions = tuning.get("exclusions") or []
    if not isinstance(exclusions, list) or len(exclusions) > MOST_EXCLUSIONS:
        raise TuningRefused(f'"exclusions" must be a list of at most {MOST_EXCLUSIONS} entries', path="exclusions")
    thresholds = tuning.get("thresholds") or {}
    if not isinstance(thresholds, dict) or not set(thresholds) <= set(THRESHOLDS) or not all(
            type(score) is int and 1 <= score <= HIGHEST_THRESHOLD for score in thresholds.values()):
        raise TuningRefused(f'"thresholds" maps inbound and outbound to an anomaly score from 1 to '
                            f'{HIGHEST_THRESHOLD}, got {thresholds!r}', path="thresholds")
    if type(tuning.get("detection_only", False)) is not bool:
        raise TuningRefused(f'"detection_only" is true or false, got {tuning["detection_only"]!r}',
                            path="detection_only")
    return {"paranoia": paranoia,
            "exclusions": [_exclusion(entry, f"exclusions[{at}]") for at, entry in enumerate(exclusions)],
            **({"thresholds": thresholds} if thresholds else {}),
            **({"detection_only": True} if tuning.get("detection_only") else {})}

def _exclusion(entry, at: str) -> dict:
    entry = entry if isinstance(entry, dict) else {}
    rule_id, target, path, tag = entry.get("rule_id"), entry.get("target") or "", entry.get("path") or "", entry.get("tag")
    if tag is not None and not (isinstance(tag, str) and TAG.fullmatch(tag) and target):
        raise TuningRefused(f'"tag" must name a CRS tag such as attack-sqli and come with a target, got {tag!r}',
                            path=f"{at}.tag")
    if tag is None and (type(rule_id) is not int or not 900000 <= rule_id <= 999999):
        raise TuningRefused(f'"rule_id" must be a CRS rule id from 900000 to 999999, got {rule_id!r}',
                            path=f"{at}.rule_id")
    if not isinstance(target, str) or (target and not TARGET.fullmatch(target)):
        raise TuningRefused(f'"target" must name a variable such as ARGS:q, got {target!r}', path=f"{at}.target")
    if not isinstance(path, str) or (path and not PATH.fullmatch(path)):
        raise TuningRefused(f'"path" must be a URL path such as /search/, got {path!r}', path=f"{at}.path")
    return {"tag": tag, "target": target, "path": path} if tag else {"rule_id": rule_id, "target": target, "path": path}

def rendered(tuning: dict) -> str:
    level = tuning["paranoia"]
    lines = [
        f'SecAction "id:{FIRST_ID},phase:1,pass,nolog,'
        f'setvar:tx.blocking_paranoia_level={level},setvar:tx.detection_paranoia_level={level}'
        + "".join(f",setvar:tx.{way}_anomaly_score_threshold={score}"
                  for way, score in sorted(tuning.get("thresholds", {}).items()))
        + (",ctl:ruleEngine=DetectionOnly" if tuning.get("detection_only") else "") + '"'
    ]
    for offset, entry in enumerate(tuning["exclusions"], start=1):
        control = (f"ruleRemoveTargetByTag={entry['tag']};{entry['target']}" if entry.get("tag")
                   else f"ruleRemoveTargetById={entry['rule_id']};{entry['target']}"
                   if entry["target"] else f"ruleRemoveById={entry['rule_id']}")
        actions = f"id:{FIRST_ID + offset},phase:1,pass,nolog,ctl:{control}"
        lines.append(f'SecRule REQUEST_FILENAME "@beginsWith {entry["path"]}" "{actions}"'
                     if entry["path"] else f'SecAction "{actions}"')
    return "\n".join(lines) + "\n"

def read(gateway, config: WafConfig = WafConfig()) -> dict:
    ran = gateway(["sh", "-c", f"cat {config.rules} 2>/dev/null || true"])
    if not ran.ok:
        raise WafUnreadable(f"could not read {config.rules}: {ran.output.strip()[-300:]}")
    return parsed(ran.output) | {"file": ran.output}

def parsed(text: str) -> dict:
    lines = [line for line in text.replace("\\\n", "").splitlines() if not line.lstrip().startswith("#")]
    level = LEVEL.search("\n".join(lines))
    exclusions = []
    for line in lines:
        path = BEGINS.search(line)
        for rule, target, whole, tag, tagged in REMOVED.findall(line):
            exclusions.append(({"tag": tag, "target": tagged} if tag else {"rule_id": int(rule or whole), "target": target})
                              | {"path": path.group(1) if path else ""})
    thresholds = {way: int(score) for way, score in THRESHOLD.findall("\n".join(lines))}
    return {"paranoia": int(level.group(1)) if level else None, "exclusions": exclusions,
            **({"thresholds": thresholds} if thresholds else {}),
            **({"detection_only": True} if "ctl:ruleEngine=DetectionOnly" in "\n".join(lines) else {})}

LIMIT_ZONE = re.compile(r"(?:^|[;{}\s])limit_req_zone\s+([^;]*);")
ZONE_NAME = re.compile(r"\bzone=([^\s:;]+):")
ZONE_RATE = re.compile(r"\brate=(\d+)r/([sm])\b")


def limit_rates_in(text: str) -> dict[str, int]:
    kept = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    rates = {}
    for arguments in LIMIT_ZONE.findall(kept):
        name, rate = ZONE_NAME.search(arguments), ZONE_RATE.search(arguments)
        if name and rate:
            rates[name.group(1)] = int(rate.group(1)) * (60 if rate.group(2) == "s" else 1)
    return rates


def limit_rates(gateway) -> dict[str, int]:
    ran = gateway(["sh", "-c", "nginx -T 2>/dev/null"])
    if not ran.ok:
        raise WafUnreadable(f"could not read the nginx configuration: {ran.output.strip()[-300:]}")
    return limit_rates_in(ran.output)

def apply(tuning, gateway, config: WafConfig = WafConfig()) -> dict:
    tuning = checked(tuning)
    previous = read(gateway, config)["file"]
    old = _workers(gateway, config)
    _write(gateway, rendered(tuning), config)
    ran = gateway(["sh", "-c", config.reload])
    if not ran.ok:
        _write(gateway, previous, config)
        raise TuningRefused("nginx refused the tuning, rolled back: " + ran.output.strip())
    for _ in range(SETTLE_POLLS):
        if _workers(gateway, config) - old:
            return tuning
        time.sleep(0.1)
    _write(gateway, previous, config)
    gateway(["sh", "-c", config.reload])
    raise TuningRefused("nginx started no worker on the new tuning, rolled back")

def reloaded_since_written(gateway, config: WafConfig = WafConfig()) -> bool:
    said = gateway(["sh", "-c", f"date +%s.%N; date -r {config.rules} +%s.%N; cut -d' ' -f1 /proc/uptime; getconf CLK_TCK; "
                                f"for w in $({workers_of(config.pid)}); do cut -d' ' -f22 /proc/$w/stat; done"]).output.split()
    if len(said) < 5 or not all(re.fullmatch(r"\d+(\.\d+)?", word) for word in said):
        return False
    now, written, uptime, ticks, *started = map(float, said)
    return any(uptime - start / ticks < now - written for start in started)

def _workers(gateway, config: WafConfig) -> set[str]:
    return set(gateway(["sh", "-c", workers_of(config.pid)]).output.split())

def _write(gateway, content: str, config: WafConfig) -> None:
    ran = gateway(["sh", "-c", "cat > " + config.rules], stdin=content)
    if not ran.ok:
        raise TuningRefused(f"could not write {config.rules}: {ran.output.strip()}")


NGINX_ERROR = re.compile(r"\[(?:emerg|alert|crit|error)\]\s*(?P<message>.*?)(?: in (?P<file>\S+):(?P<line>\d+))?$")
LOOPBACK = "127.0.0.1"
PROBE_TIMEOUT = 15
SCRATCH_TIMEOUT = 600.0


@dataclass(frozen=True)
class Scratch:
    prefix: str
    port: int
    upstream_port: int

    @property
    def tree(self) -> str:
        return f"{self.prefix}/modsecurity"

    @property
    def conf(self) -> str:
        return f"{self.prefix}/nginx.conf"

    @property
    def audit(self) -> str:
        return f"{self.prefix}/logs/audit.log"


def field_errors(refused: TuningRefused) -> list[dict]:
    return [error.shown() for error in refused.errors]


def scratch_for(config: WafConfig, test_id: int) -> Scratch:
    number = int(test_id)
    if number < 1:
        raise ValueError(f"a scratch test is named by a positive RuleTest id, got {test_id!r}")
    prefix = PurePosixPath(config.scratch) / f"test-{number}"
    for live in (PurePosixPath(config.tree), PurePosixPath(config.rules).parent):
        if prefix == live or live in prefix.parents or prefix in live.parents:
            raise ValueError(f"the scratch prefix {prefix} must lie apart from the live CRS tree {live}")
    port = config.first_port + number % 1000
    return Scratch(prefix=str(prefix), port=port, upstream_port=port + 1000)


def _relative_rules(config: WafConfig) -> str:
    return str(PurePosixPath(config.rules).relative_to(config.tree))


def _prepared(tuning: dict, gateway, config: WafConfig, scratch: Scratch) -> None:
    rendered_into = f"{scratch.tree}/{_relative_rules(config)}"
    script = (
        f"set -e; rm -rf {scratch.prefix}; mkdir -p {scratch.prefix}/logs {scratch.prefix}/run; "
        f"cp -a {shlex.quote(config.tree)} {scratch.tree}; "
        f"sed -i -e 's#{config.tree}#{scratch.tree}#g' -e 's#^SecAuditLog .*#SecAuditLog {scratch.audit}#' "
        f"{scratch.tree}/modsecurity.conf; "
        f"sed -e 's#@prefix@#{scratch.prefix}#g' -e 's#@port@#{scratch.port}#g' "
        f"-e 's#@upstream_port@#{scratch.upstream_port}#g' {shlex.quote(config.probe_template)} > {scratch.conf}; "
        f"cat > {rendered_into}"
    )
    ran = gateway(["sh", "-c", script], stdin=rendered(tuning))
    if not ran.ok:
        _removed(gateway, scratch)
        raise TuningRefused(f"the WAF could not lay out a scratch CRS instance: {ran.output.strip()[-300:]}")


def nginx_errors(output: str) -> list[dict]:
    found = []
    for line in output.splitlines():
        matched = NGINX_ERROR.search(line.strip())
        if matched:
            found.append({"line": int(matched["line"]) if matched["line"] else None,
                          "message": matched["message"].strip()})
    return found


def _tested(gateway, scratch: Scratch) -> list[dict]:
    ran = gateway(["sh", "-c", f"nginx -t -p {scratch.prefix} -c {scratch.conf} 2>&1"])
    if ran.ok:
        return []
    return nginx_errors(ran.output) or [{"line": None, "message": ran.output.strip()[-500:]}]


def _removed(gateway, scratch: Scratch) -> None:
    gateway(["sh", "-c", f"rm -rf {scratch.prefix}"])


def _refused(errors: list[dict]) -> TuningRefused:
    return TuningRefused("nginx refused the scratch configuration: " + "; ".join(e["message"] for e in errors),
                         errors=tuple(FieldError(path="posture", code=TuningRefused.code, line=error["line"],
                                                 params={"message": error["message"]}) for error in errors))


def scratch_check(tuning, gateway, config: WafConfig, test_id: int) -> list[dict]:
    tuning = checked(tuning)
    scratch = scratch_for(config, test_id)
    _prepared(tuning, gateway, config, scratch)
    try:
        return _tested(gateway, scratch)
    finally:
        _removed(gateway, scratch)


def probe_argv(scratch: Scratch, probe: dict) -> list[str]:
    argv = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(PROBE_TIMEOUT),
            "--path-as-is", "-X", str(probe.get("method") or "GET"),
            "-H", f"Host: {probe.get('host') or 'localhost'}", "-H", f"X-Request-ID: {probe['marker']}"]
    for name, value in (probe.get("headers") or {}).items():
        if name.lower() not in ("host", "x-request-id", "content-length"):
            argv += ["-H", f"{name}: {value}"]
    if probe.get("body") is not None:
        argv += ["--data-binary", "@-"]
    return argv + [f"http://{LOOPBACK}:{scratch.port}{probe.get('path') or '/'}"]


def audit_alerts(text: str) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        transaction = (record or {}).get("transaction") or {}
        headers = (transaction.get("request") or {}).get("headers") or {}
        marker = next((value for name, value in headers.items() if str(name).lower() == "x-request-id"), None)
        if not marker:
            continue
        for message in transaction.get("messages") or ():
            details = message.get("details") or {}
            found.setdefault(marker, []).append({"rule": str(details.get("ruleId", "")),
                                                 "signature": message.get("message", "")})
    return found


def scratch_test(tuning, gateway, config: WafConfig, test_id: int, probes: Sequence[dict]) -> dict[str, dict]:
    tuning = checked(tuning)
    scratch = scratch_for(config, test_id)
    _prepared(tuning, gateway, config, scratch)
    try:
        errors = _tested(gateway, scratch)
        if errors:
            raise _refused(errors)
        started = gateway(["sh", "-c", (
            f"set -e; cat > {scratch.prefix}/probes.json; "
            f"nohup python3 {shlex.quote(config.probe_upstream)} --port {scratch.upstream_port} "
            f"--probes {scratch.prefix}/probes.json >{scratch.prefix}/logs/upstream.log 2>&1 & "
            f"echo $! > {scratch.prefix}/run/upstream.pid; "
            f"nginx -p {scratch.prefix} -c {scratch.conf}")], stdin=json.dumps(list(probes)))
        if not started.ok:
            raise TuningRefused(f"the scratch CRS instance did not start: {started.output.strip()[-300:]}")
        statuses = {}
        for probe in probes:
            body = probe.get("body")
            ran = gateway(probe_argv(scratch, probe), stdin=body if body is not None else None,
                          timeout=PROBE_TIMEOUT + 15)
            statuses[probe["marker"]] = int(ran.output.strip()[-3:]) if ran.output.strip()[-3:].isdigit() else 0
        alerts = audit_alerts(gateway(["sh", "-c", f"cat {scratch.audit} 2>/dev/null; true"]).output)
        return {marker: {"status": status, "alerts": alerts.get(marker, [])} for marker, status in statuses.items()}
    finally:
        gateway(["sh", "-c", (f"nginx -p {scratch.prefix} -c {scratch.conf} -s stop 2>/dev/null; "
                              f"kill \"$(cat {scratch.prefix}/run/upstream.pid 2>/dev/null)\" 2>/dev/null; "
                              f"rm -rf {scratch.prefix}; true")])
