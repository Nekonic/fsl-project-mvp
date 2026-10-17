from __future__ import annotations

import difflib
import re

import suppress

ANSWER = 3
SKIP_OFFERED = 4
WRONGS_PER_HINT = 2
CRS_DEFAULT_LEVEL = 1
CRS_THRESHOLDS = {"inbound": 5, "outbound": 4}
CRS_TOTALS = ("949", "959", "980")
PASTED_ROW = re.compile(r"^\s*\|?\s*([\w.@+-]+)\s*[|:\s]\s*(\S+?)\s*\|?\s*$")

def answered(check: dict, given: str, wrong: str) -> tuple[bool, list | None]:
    if given.casefold() in {str(accepted).casefold() for accepted in check.get("accept", [])}:
        return True, None
    if given in check.get("known", []):
        return False, [f"{wrong}.{given}", []]
    return False, ["lesson.check.wrong", []]

def fix_class(waf: dict | None, posture: dict | None) -> str | None:
    if not waf:
        return None
    posture = posture or {}
    level = waf.get("paranoia") or CRS_DEFAULT_LEVEL
    if posture.get("paranoia") and level < posture["paranoia"]:
        return "level"
    if any(_threshold(waf, way) > _threshold(posture, way) for way in CRS_THRESHOLDS):
        return "threshold"
    added = [entry for entry in waf.get("exclusions") or [] if entry not in (posture.get("exclusions") or [])]
    if not added:
        return None
    if any(not entry["target"] for entry in added):
        return "rule"
    if any(not entry["path"] for entry in added):
        return "target"
    return "path_target"

def _threshold(tuning: dict, way: str) -> int:
    return (tuning.get("thresholds") or {}).get(way, CRS_THRESHOLDS[way])

def config_diff(before: str, after: str) -> list[str]:
    return [
        line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]

def exclusions_changed(before: list, after: list) -> dict:
    return {"added": [entry for entry in after if entry not in before],
            "removed": [entry for entry in before if entry not in after]}

def help_counts(steps: dict) -> dict:
    kept = list(steps.values())
    return {
        "hints": sum(1 for step in kept if step.get("hint")),
        "skipped": sum(1 for step in kept if step.get("skipped") and not step.get("passed")),
    }

def rules_named(messages: list[dict]) -> list[str]:
    found = set()
    for message in messages:
        rule = str((message.get("details") or {}).get("ruleId") or "")
        if rule and not rule.startswith(CRS_TOTALS):
            found.add(rule)
    return sorted(found)

def added_rules(live: str, baseline: str) -> list[int]:
    started = {sid: " ".join(suppress.find(baseline, sid).split()) for sid in suppress.sids(baseline)}
    return sorted(sid for sid in suppress.sids(live)
                  if started.get(sid) != " ".join(suppress.find(live, sid).split()))

def within(count: int, ratio: float) -> list[int]:
    if count <= 0:
        return []
    spread = max(2, round(count * ratio))
    return [count, *(found for found in range(max(1, count - spread), count + spread + 1) if found != count)]

def pasted_rows(text: str, parsed: list) -> list:
    return parsed or [found.groups() for found in map(PASTED_ROW.match, text.splitlines()) if found]
