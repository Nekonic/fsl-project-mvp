from __future__ import annotations

import re
import time
from typing import NamedTuple

EXCLUSIONS = "/etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
NGINX_RELOAD = "nginx -t 2>&1 && nginx -s reload 2>&1"
NGINX_PID = "/tmp/nginx.pid"

class Layout(NamedTuple):
    rules: str = EXCLUSIONS
    reload: str = NGINX_RELOAD
    pid: str = NGINX_PID

def workers_of(pid: str) -> str:
    return ('m=$(cat ' + pid + '); for d in /proc/[0-9]*; do '
            '[ "$(cut -d" " -f4 $d/stat 2>/dev/null)" = "$m" ] && echo ${d#/proc/}; done; true')

SETTLE_POLLS = 50
FIRST_ID = 10000
MOST_EXCLUSIONS = 20
TARGET = re.compile(r"(ARGS|ARGS_GET|ARGS_POST|ARGS_NAMES|REQUEST_COOKIES|REQUEST_HEADERS)(:[\w-]+)?|REQUEST_URI_RAW|REQUEST_BODY", re.ASCII)
PATH = re.compile(r"/[\w./-]*", re.ASCII)
THRESHOLDS = ("inbound", "outbound")
HIGHEST_THRESHOLD = 100000

LEVEL = re.compile(r"tx\.blocking_paranoia_level=([1-4])\b")
REMOVED = re.compile(r"ctl:ruleRemove(?:TargetById=(\d+);([\w:-]+)|ById=(\d+))")
BEGINS = re.compile(r'"@beginsWith (/[\w./-]*)"')
THRESHOLD = re.compile(r"tx\.(inbound|outbound)_anomaly_score_threshold=(\d+)")

class TuningRefused(ValueError):
    pass

def checked(tuning) -> dict:
    if not isinstance(tuning, dict):
        raise TuningRefused("the tuning is an object with paranoia and exclusions")
    paranoia = tuning.get("paranoia")
    if type(paranoia) is not int or not 1 <= paranoia <= 4:
        raise TuningRefused(f'"paranoia" must be a paranoia level from 1 to 4, got {paranoia!r}')
    exclusions = tuning.get("exclusions") or []
    if not isinstance(exclusions, list) or len(exclusions) > MOST_EXCLUSIONS:
        raise TuningRefused(f'"exclusions" must be a list of at most {MOST_EXCLUSIONS} entries')
    thresholds = tuning.get("thresholds") or {}
    if not isinstance(thresholds, dict) or not set(thresholds) <= set(THRESHOLDS) or not all(
            type(score) is int and 1 <= score <= HIGHEST_THRESHOLD for score in thresholds.values()):
        raise TuningRefused(f'"thresholds" maps inbound and outbound to an anomaly score from 1 to '
                            f'{HIGHEST_THRESHOLD}, got {thresholds!r}')
    return {"paranoia": paranoia, "exclusions": [_exclusion(entry) for entry in exclusions],
            **({"thresholds": thresholds} if thresholds else {})}

def _exclusion(entry) -> dict:
    entry = entry if isinstance(entry, dict) else {}
    rule_id, target, path = entry.get("rule_id"), entry.get("target") or "", entry.get("path") or ""
    if type(rule_id) is not int or not 900000 <= rule_id <= 999999:
        raise TuningRefused(f'"rule_id" must be a CRS rule id from 900000 to 999999, got {rule_id!r}')
    if not isinstance(target, str) or (target and not TARGET.fullmatch(target)):
        raise TuningRefused(f'"target" must name a variable such as ARGS:q, got {target!r}')
    if not isinstance(path, str) or (path and not PATH.fullmatch(path)):
        raise TuningRefused(f'"path" must be a URL path such as /search/, got {path!r}')
    return {"rule_id": rule_id, "target": target, "path": path}

def rendered(tuning: dict) -> str:
    level = tuning["paranoia"]
    lines = [
        f'SecAction "id:{FIRST_ID},phase:1,pass,nolog,'
        f'setvar:tx.blocking_paranoia_level={level},setvar:tx.detection_paranoia_level={level}'
        + "".join(f",setvar:tx.{way}_anomaly_score_threshold={score}"
                  for way, score in sorted(tuning.get("thresholds", {}).items())) + '"'
    ]
    for offset, entry in enumerate(tuning["exclusions"], start=1):
        control = (f"ruleRemoveTargetById={entry['rule_id']};{entry['target']}"
                   if entry["target"] else f"ruleRemoveById={entry['rule_id']}")
        actions = f"id:{FIRST_ID + offset},phase:1,pass,nolog,ctl:{control}"
        lines.append(f'SecRule REQUEST_FILENAME "@beginsWith {entry["path"]}" "{actions}"'
                     if entry["path"] else f'SecAction "{actions}"')
    return "\n".join(lines) + "\n"

def read(gateway, layout: Layout = Layout()) -> dict:
    text = gateway(["sh", "-c", f"cat {layout.rules} 2>/dev/null || true"]).output
    return parsed(text) | {"file": text}

def parsed(text: str) -> dict:
    lines = [line for line in text.replace("\\\n", "").splitlines() if not line.lstrip().startswith("#")]
    level = LEVEL.search("\n".join(lines))
    exclusions = []
    for line in lines:
        path = BEGINS.search(line)
        for rule, target, whole in REMOVED.findall(line):
            exclusions.append({"rule_id": int(rule or whole), "target": target,
                               "path": path.group(1) if path else ""})
    thresholds = {way: int(score) for way, score in THRESHOLD.findall("\n".join(lines))}
    return {"paranoia": int(level.group(1)) if level else None, "exclusions": exclusions,
            **({"thresholds": thresholds} if thresholds else {})}

def apply(tuning, gateway, layout: Layout = Layout()) -> dict:
    tuning = checked(tuning)
    previous = read(gateway, layout)["file"]
    old = _workers(gateway, layout)
    _write(gateway, rendered(tuning), layout)
    ran = gateway(["sh", "-c", layout.reload])
    if not ran.ok:
        _write(gateway, previous, layout)
        raise TuningRefused("nginx refused the tuning, rolled back: " + ran.output.strip())
    for _ in range(SETTLE_POLLS):
        if _workers(gateway, layout) - old:
            return tuning
        time.sleep(0.1)
    _write(gateway, previous, layout)
    gateway(["sh", "-c", layout.reload])
    raise TuningRefused("nginx started no worker on the new tuning, rolled back")

def _workers(gateway, layout: Layout) -> set[str]:
    return set(gateway(["sh", "-c", workers_of(layout.pid)]).output.split())

def _write(gateway, content: str, layout: Layout) -> None:
    ran = gateway(["sh", "-c", "cat > " + layout.rules], stdin=content)
    if not ran.ok:
        raise TuningRefused(f"could not write {layout.rules}: {ran.output.strip()}")
