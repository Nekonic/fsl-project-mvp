from __future__ import annotations

import re
import time

EXCLUSIONS = "/etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
RELOAD = ["sh", "-c", "nginx -t 2>&1 && nginx -s reload 2>&1"]
WORKERS = ('m=$(cat /tmp/nginx.pid); for d in /proc/[0-9]*; do '
           '[ "$(cut -d" " -f4 $d/stat 2>/dev/null)" = "$m" ] && echo ${d#/proc/}; done; true')
SETTLE_POLLS = 50
FIRST_ID = 10000
MOST_EXCLUSIONS = 20
TARGET = re.compile(r"(ARGS|ARGS_GET|ARGS_POST|ARGS_NAMES|REQUEST_COOKIES|REQUEST_HEADERS)(:[\w-]+)?", re.ASCII)
PATH = re.compile(r"/[\w./-]*", re.ASCII)

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
    return {"paranoia": paranoia, "exclusions": [_exclusion(entry) for entry in exclusions]}

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
        f'setvar:tx.blocking_paranoia_level={level},setvar:tx.detection_paranoia_level={level}"'
    ]
    for offset, entry in enumerate(tuning["exclusions"], start=1):
        control = (f"ruleRemoveTargetById={entry['rule_id']};{entry['target']}"
                   if entry["target"] else f"ruleRemoveById={entry['rule_id']}")
        actions = f"id:{FIRST_ID + offset},phase:1,pass,nolog,ctl:{control}"
        lines.append(f'SecRule REQUEST_FILENAME "@beginsWith {entry["path"]}" "{actions}"'
                     if entry["path"] else f'SecAction "{actions}"')
    return "\n".join(lines) + "\n"

def apply(tuning, gateway) -> dict:
    tuning = checked(tuning)
    previous = gateway(["sh", "-c", f"cat {EXCLUSIONS} 2>/dev/null || true"]).output
    old = _workers(gateway)
    _write(gateway, rendered(tuning))
    ran = gateway(RELOAD)
    if not ran.ok:
        _write(gateway, previous)
        raise TuningRefused("nginx refused the tuning, rolled back: " + ran.output.strip())
    for _ in range(SETTLE_POLLS):
        if _workers(gateway) - old:
            return tuning
        time.sleep(0.1)
    _write(gateway, previous)
    gateway(RELOAD)
    raise TuningRefused("nginx started no worker on the new tuning, rolled back")

def _workers(gateway) -> set[str]:
    return set(gateway(["sh", "-c", WORKERS]).output.split())

def _write(gateway, content: str) -> None:
    ran = gateway(["sh", "-c", "cat > " + EXCLUSIONS], stdin=content)
    if not ran.ok:
        raise TuningRefused(f"could not write {EXCLUSIONS}: {ran.output.strip()}")
