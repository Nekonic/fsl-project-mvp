from __future__ import annotations

import difflib
import re

import suppress

ANSWER = 3
SKIP_OFFERED = 4
SKIP_OFFERED_IN_FOUNDATIONS = 3
WRONGS_PER_HINT = 2
CRS_DEFAULT_LEVEL = 1
CRS_THRESHOLDS = {"inbound": 5, "outbound": 4}
CRS_TOTALS = ("949", "959", "980")
PASTED_ROW = re.compile(r"^\s*\|?\s*([\w.@+-]+)\s*[|:\s]\s*(\S+?)\s*\|?\s*$")
ORDER_SEPARATOR = re.compile(r"[\s,>\u2192]+")
TOTAL_SCORE = re.compile(r"Total Score: (\d+)")
NOCASE = re.compile(r"\bnocase\s*;|\bpcre\s*:\s*\"/.*/[A-Za-z]*i[A-Za-z]*\"")
BLOCKING_RULE = "949110"
PRESENT, ABSENT = "present", "absent"
YES, NO = "yes", "no"
ALERTED_BY = {frozenset(): "none", frozenset({"suricata"}): "ids", frozenset({"modsecurity"}): "waf",
              frozenset({"suricata", "modsecurity"}): "both"}

def answered(check: dict, given: str, wrong: str) -> tuple[bool, list | None]:
    accepted = [_bare(str(value)) for value in check.get("accept", [])]
    if check.get("form") == "order":
        named = [_bare(name) for name in ORDER_SEPARATOR.split(given) if name]
        if named == accepted:
            return True, None
        if sorted(named) == sorted(accepted):
            return False, [f"{wrong}.order", []]
    elif _bare(given) in accepted:
        return True, None
    if given in check.get("known", []):
        return False, [f"{wrong}.{given}", []]
    said = next((rule["says"] for rule in check.get("wrong_if", []) if re.search(rule["match"], given)), None)
    return False, [f"{wrong}.{said}" if said else "lesson.check.wrong", []]

def _bare(text: str) -> str:
    return "".join(text.split()).casefold()

def anomaly_totals(messages: list[str]) -> list[str]:
    return [found[1] for found in map(TOTAL_SCORE.search, messages) if found]

def ignores_case(rule: str) -> bool:
    return bool(NOCASE.search(rule))

def alerted_by(engines: set[str]) -> str:
    return ALERTED_BY[frozenset(engines) & frozenset({"suricata", "modsecurity"})]

def penalty(difficulty: int, detected: bool) -> int:
    return difficulty * (1 if detected else 2)

def detected_penalty(tiers: list[dict], key: str) -> int | None:
    found = next((tier for tier in tiers if tier.get("key") == key), None)
    return penalty(int(found["difficulty"]), True) if found else None

def rule_of(raw: dict) -> str:
    return str((raw.get("details") or {}).get("ruleId") or (raw.get("alert") or {}).get("signature_id") or "")

def server_errors(records: list[dict]) -> int:
    return sum(1 for record in records
               if str(((record.get("transaction") or {}).get("response") or {}).get("http_code") or "") == "500")

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

def records(lesson_steps: dict | None, lesson_id: str) -> dict:
    return (lesson_steps or {}).get(lesson_id) or {}

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

def pasted_rows(text: str, parsed: list) -> list:
    return parsed or [found.groups() for found in map(PASTED_ROW.match, text.splitlines()) if found]
