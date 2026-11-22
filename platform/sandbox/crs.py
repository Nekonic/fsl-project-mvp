from __future__ import annotations

import base64
import binascii
import json
import re
import shlex
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from cr.config import WafConfig
from cr.errors import EngineRefused, FieldError, Unavailable

SETTLE_POLLS = 50
MOST_BYTES = 200000
READ_FILES = 'for f in "$@"; do base64 -w0 "$f" 2>/dev/null; echo; done'
WRITE_FILE = 'cat > "$1"'
READ_SNAPSHOT = ('d=$1; shift; exec 9>>"$d.lock"; flock -s 9; cat "$d/at" || exit 1; '
                 'for f in "$@"; do base64 -w0 "$d$f" || exit 1; echo; done')
CRS_SETUP = "crs-setup.conf"
DETECTION_ONLY = "SecRuleEngine DetectionOnly"
NGINX_MEASUREMENT = re.compile(r"(?:^|[\s;{}])(access_log|log_format|error_log|open_log_file_cache"
                               r"|set_real_ip_from|real_ip_header|real_ip_recursive)\b")
MODSECURITY_MEASUREMENT = re.compile(r"\b(SecAudit\w*|SecDebugLog\w*|ctl:audit\w*)", re.IGNORECASE)
NGINX_ERROR = re.compile(r"\[(?:emerg|alert|crit|error)\]\s*(?P<message>.*?)(?: in (?P<file>\S+):(?P<line>\d+))?$")
RULES_ERROR = re.compile(r"File: (?P<file>\S+?)\.? Line: (?P<line>\d+)")
PROXIED = re.compile(r"proxy_pass\s+[^;]+;")
LOOPBACK = "127.0.0.1"
PROBE_TIMEOUT = 15
SCRATCH_TIMEOUT = 600.0


def workers_of(pid: str) -> str:
    return ('m=$(cat ' + pid + '); for d in /proc/[0-9]*; do '
            '[ "$(cut -d" " -f4 $d/stat 2>/dev/null)" = "$m" ] && echo ${d#/proc/}; done; true')


class WafRefused(EngineRefused, ValueError):
    code = "crs_refused"


class WafUnreadable(Unavailable):
    code = "waf_unavailable"


@dataclass(frozen=True)
class Reloaded:
    files: dict[str, str]
    at: float


def problem(file: str | None, line: int | None, message: str) -> dict:
    return {"file": file, "line": line, "message": message}


def refused(message: str, found: Sequence[dict]) -> WafRefused:
    return WafRefused(message, errors=tuple(
        FieldError(path=one["file"] or "files", code=WafRefused.code, line=one["line"],
                   params={"message": one["message"]}) for one in found))


def measurement_in(path: str, text: str) -> list[dict]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        kept = line.split("#", 1)[0]
        named = NGINX_MEASUREMENT.search(kept) or MODSECURITY_MEASUREMENT.search(kept)
        if named:
            found.append(problem(path, number, f"{named.group(1)} is the platform's measurement and stays as it is"))
    return found


def editable(config: WafConfig = WafConfig()) -> list[str]:
    return list(config.files)


def refusals(files: object, config: WafConfig = WafConfig()) -> list[dict]:
    if not isinstance(files, Mapping):
        return [problem(None, None, "the WAF files are an object of file path to file text")]
    found = []
    for path, text in files.items():
        if path not in config.files:
            found.append(problem(path, None, "this file is not one the defence edits: " + ", ".join(config.files)))
        elif not isinstance(text, str) or len(text) > MOST_BYTES:
            found.append(problem(path, None, f"a file is a text of at most {MOST_BYTES} characters"))
        else:
            found += measurement_in(path, text)
    return found


def checked(files: object, config: WafConfig) -> dict[str, str]:
    found = refusals(files, config)
    if found:
        raise refused("the WAF files were refused: " + "; ".join(one["message"] for one in found), found)
    return dict(files)


def read(gateway, config: WafConfig = WafConfig()) -> dict[str, str]:
    ran = gateway(["sh", "-c", READ_FILES, "sh", *config.files])
    if not ran.ok:
        raise WafUnreadable(f"could not read the WAF files: {ran.output.strip()[-300:]}")
    return _decoded(ran.output.split("\n"), config)


def _decoded(lines: Sequence[str], config: WafConfig) -> dict[str, str]:
    if len(lines) < len(config.files):
        raise WafUnreadable("the WAF files came back short")
    try:
        return {path: base64.b64decode(line.strip(), validate=True).decode("utf-8", errors="replace")
                for path, line in zip(config.files, lines)}
    except binascii.Error as garbled:
        raise WafUnreadable("the WAF files came back garbled") from garbled


def detection_only(files: Mapping[str, str], config: WafConfig) -> dict[str, str]:
    setup = next(path for path in config.files if PurePosixPath(path).name == CRS_SETUP)
    return {**files, setup: files.get(setup, "").rstrip("\n") + f"\n{DETECTION_ONLY}\n"}


LIMIT_ZONE = re.compile(r"(?:^|[;{}\s])limit_req_zone\s+([^;]*);")
ZONE_NAME = re.compile(r"\bzone=([^\s:;]+):")
ZONE_RATE = re.compile(r"\brate=(\d+)r/([sm])\b")
PER_CLIENT_KEY = re.compile(r"\$(?:binary_)?remote_addr\b")


def limit_rates_in(text: str) -> dict[str, int]:
    kept = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    rates = {}
    for arguments in LIMIT_ZONE.findall(kept):
        name, rate = ZONE_NAME.search(arguments), ZONE_RATE.search(arguments)
        if name and rate and PER_CLIENT_KEY.search(arguments.split()[0]):
            rates[name.group(1)] = int(rate.group(1)) * (60 if rate.group(2) == "s" else 1)
    return rates


def limit_rates(gateway) -> dict[str, int]:
    ran = gateway(["sh", "-c", "nginx -T 2>/dev/null"])
    if not ran.ok:
        raise WafUnreadable(f"could not read the nginx configuration: {ran.output.strip()[-300:]}")
    return limit_rates_in(ran.output)


def nginx_errors(output: str, moved: Mapping[str, str] | None = None) -> list[dict]:
    found = []
    for line in output.splitlines():
        matched = NGINX_ERROR.search(line.strip())
        if not matched:
            continue
        rules = RULES_ERROR.search(matched["message"])
        file, number = (rules["file"], rules["line"]) if rules else (matched["file"], matched["line"])
        found.append(problem(_moved_back(file, moved or {}), int(number) if number else None,
                             matched["message"].strip()))
    return found


def _moved_back(file: str | None, moved: Mapping[str, str]) -> str | None:
    if file is None:
        return None
    for scratch, live in moved.items():
        if file == scratch or file.startswith(scratch + "/"):
            return live + file[len(scratch):]
    return file


def apply(files, gateway, config: WafConfig = WafConfig()) -> dict[str, str]:
    given = checked(files, config)
    previous = read(gateway, config)
    merged = previous | given
    changed = {path: text for path, text in merged.items() if previous.get(path) != text}
    old = _workers(gateway, config)
    _write(gateway, changed)
    ran = gateway(["sh", "-c", config.reload])
    if not ran.ok:
        _write(gateway, {path: previous[path] for path in changed})
        found = nginx_errors(ran.output) or [problem(None, None, ran.output.strip()[-500:])]
        raise refused("nginx refused the WAF files, rolled back: " + ran.output.strip(), found)
    for _ in range(SETTLE_POLLS):
        if _workers(gateway, config) - old:
            return merged
        time.sleep(0.1)
    _write(gateway, {path: previous[path] for path in changed})
    gateway(["sh", "-c", config.reload])
    raise refused("nginx started no worker on the new files, rolled back",
                  [problem(None, None, "nginx started no worker on the new files, rolled back")])


def reloaded(gateway, config: WafConfig = WafConfig()) -> Reloaded | None:
    ran = gateway(["sh", "-c", READ_SNAPSHOT, "sh", config.snapshot, *config.files])
    at, _, rest = ran.output.partition("\n")
    if not ran.ok or not re.fullmatch(r"\d+(\.\d+)?", at.strip()):
        return None
    try:
        return Reloaded(files=_decoded(rest.split("\n"), config), at=float(at))
    except WafUnreadable:
        return None


def _workers(gateway, config: WafConfig) -> set[str]:
    return set(gateway(["sh", "-c", workers_of(config.pid)]).output.split())


def _write(gateway, files: Mapping[str, str]) -> None:
    for path, text in files.items():
        ran = gateway(["sh", "-c", WRITE_FILE, "sh", path], stdin=text)
        if not ran.ok:
            raise refused(f"could not write {path}: {ran.output.strip()}",
                          [problem(path, None, f"could not write {path}: {ran.output.strip()[-300:]}")])


@dataclass(frozen=True)
class Scratch:
    prefix: str
    port: int
    upstream_port: int

    @property
    def tree(self) -> str:
        return f"{self.prefix}/modsecurity"

    @property
    def sites(self) -> str:
        return f"{self.prefix}/sites"

    @property
    def conf(self) -> str:
        return f"{self.prefix}/nginx.conf"

    @property
    def audit(self) -> str:
        return f"{self.prefix}/logs/audit.log"


def scratch_for(config: WafConfig, test_id: int) -> Scratch:
    number = int(test_id)
    if number < 1:
        raise ValueError(f"a scratch test is named by a positive RuleTest id, got {test_id!r}")
    prefix = PurePosixPath(config.scratch) / f"test-{number}"
    for live in (PurePosixPath(config.tree), PurePosixPath(config.sites),
                 *(PurePosixPath(path).parent for path in config.files)):
        if prefix == live or live in prefix.parents or prefix in live.parents:
            raise ValueError(f"the scratch prefix {prefix} must lie apart from the live WAF files under {live}")
    port = config.first_port + number % 1000
    return Scratch(prefix=str(prefix), port=port, upstream_port=port + 1000)


def scratch_path(path: str, config: WafConfig, scratch: Scratch) -> str:
    for live, laid in ((config.tree, scratch.tree), (config.sites, scratch.sites)):
        if PurePosixPath(live) in PurePosixPath(path).parents:
            return laid + path[len(live):]
    raise ValueError(f"{path} lies outside the CRS tree {config.tree} and the nginx files {config.sites}")


def _moved(config: WafConfig, scratch: Scratch) -> dict[str, str]:
    return {scratch.tree: config.tree, scratch.sites: config.sites}


def _prepared(files: Mapping[str, str], gateway, config: WafConfig, scratch: Scratch) -> None:
    script = (
        f"set -e; rm -rf {scratch.prefix}; mkdir -p {scratch.prefix}/logs {scratch.prefix}/run; "
        f"cp -a {shlex.quote(config.tree)} {scratch.tree}; cp -a {shlex.quote(config.sites)} {scratch.sites}; "
        f"sed -i -e 's#{config.tree}#{scratch.tree}#g' -e 's#^SecAuditLog .*#SecAuditLog {scratch.audit}#' "
        f"{scratch.tree}/modsecurity.conf; "
        f"sed -e 's#@prefix@#{scratch.prefix}#g' -e 's#@port@#{scratch.port}#g' "
        f"-e 's#@upstream_port@#{scratch.upstream_port}#g' {shlex.quote(config.probe_template)} > {scratch.conf}; "
        f"find {scratch.sites} -name '*.conf' -exec sed -i -E "
        f"'s#proxy_pass[[:space:]]+[^;]+;#proxy_pass http://{LOOPBACK}:{scratch.upstream_port};#g' {{}} +"
    )
    ran = gateway(["sh", "-c", script])
    if ran.ok:
        for path, text in files.items():
            ran = gateway(["sh", "-c", WRITE_FILE, "sh", scratch_path(path, config, scratch)],
                          stdin=PROXIED.sub(f"proxy_pass http://{LOOPBACK}:{scratch.upstream_port};", text))
            if not ran.ok:
                break
    if not ran.ok:
        _removed(gateway, scratch)
        raise refused(f"the WAF could not lay out a scratch instance: {ran.output.strip()[-300:]}",
                      [problem(None, None, f"the WAF could not lay out a scratch instance: {ran.output.strip()[-300:]}")])


def _tested(gateway, config: WafConfig, scratch: Scratch) -> list[dict]:
    ran = gateway(["sh", "-c", f"nginx -t -p {scratch.prefix} -c {scratch.conf} 2>&1"])
    if ran.ok:
        return []
    return nginx_errors(ran.output, _moved(config, scratch)) or [problem(None, None, ran.output.strip()[-500:])]


def _removed(gateway, scratch: Scratch) -> None:
    gateway(["sh", "-c", f"rm -rf {scratch.prefix}"])


def scratch_check(files, gateway, config: WafConfig, test_id: int) -> list[dict]:
    found = refusals(files, config)
    if found:
        return found
    scratch = scratch_for(config, test_id)
    _prepared(files, gateway, config, scratch)
    try:
        return _tested(gateway, config, scratch)
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


def scratch_test(files, gateway, config: WafConfig, test_id: int, probes: Sequence[dict]) -> dict[str, dict]:
    given = checked(files, config)
    scratch = scratch_for(config, test_id)
    _prepared(given, gateway, config, scratch)
    try:
        found = _tested(gateway, config, scratch)
        if found:
            raise refused("nginx refused the scratch configuration: " + "; ".join(one["message"] for one in found),
                          found)
        started = gateway(["sh", "-c", (
            f"set -e; cat > {scratch.prefix}/probes.json; "
            f"nohup python3 {shlex.quote(config.probe_upstream)} --port {scratch.upstream_port} "
            f"--probes {scratch.prefix}/probes.json >{scratch.prefix}/logs/upstream.log 2>&1 & "
            f"echo $! > {scratch.prefix}/run/upstream.pid; "
            f"nginx -p {scratch.prefix} -c {scratch.conf}")], stdin=json.dumps(list(probes)))
        if not started.ok:
            raise refused(f"the scratch WAF did not start: {started.output.strip()[-300:]}",
                          [problem(None, None, f"the scratch WAF did not start: {started.output.strip()[-300:]}")])
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
