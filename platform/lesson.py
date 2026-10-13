from __future__ import annotations

import difflib
import re

import suppress

ANSWER = 3
DO_IT = 4
WRONGS_PER_HINT = 2
CRS_DEFAULT_LEVEL = 1
CRS_TOTALS = ("949", "959", "980")
PASTED_ROW = re.compile(r"^\s*\|?\s*([\w.@+-]+)\s*[|:\s]\s*(\S+?)\s*\|?\s*$")
VARIABLE = re.compile(r"against variable `([^']+)'|found within ([A-Z_]+(?::[^:\s]+)?)|^([A-Z_]+:[^=\s]+)=")

def answered(check: dict, given: str, wrong: str) -> tuple[bool, list | None]:
    if given.casefold() in {str(accepted).casefold() for accepted in check.get("accept", [])}:
        return True, None
    if given in check.get("known", []):
        return False, [f"{wrong}.{given}", []]
    return False, ["lesson.check.wrong", []]

def fix_class(waf: dict | None, posture: dict | None, scope: str) -> str | None:
    if not waf:
        return None
    posture = posture or {}
    level = waf.get("paranoia") or CRS_DEFAULT_LEVEL
    if posture.get("paranoia") and level < posture["paranoia"]:
        return "level"
    added = [entry for entry in waf.get("exclusions") or [] if entry not in (posture.get("exclusions") or [])]
    if not added:
        return None
    if any(not entry["target"] for entry in added):
        return "rule"
    if any(not (entry["path"] and entry["path"].startswith(scope)) for entry in added):
        return "target"
    return "path_target"

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
        "done_for_me": sum(1 for step in kept if step.get("done_for_me")),
    }

def risks(fix: str | None, attacks: int) -> list:
    return ([[f"lesson.risk.{fix}", []]] if fix else []) + [["lesson.risk.replayed", [attacks]]]

def served(status: int) -> bool:
    return 200 <= status < 300

def outcome(row: dict) -> str:
    if row["malicious"]:
        return row["outcome"]
    return "served" if served(row["status"]) else "blocked"

def verdict(rows: list[dict]) -> tuple[bool, list]:
    attacks = [row for row in rows if row["malicious"]]
    held = [row for row in attacks if row["outcome"] == "held"]
    diagnosis = [["lesson.diag.blocked_ratio", [len(held), len(attacks)]]]
    for row in rows:
        if outcome(row) == "leaked":
            diagnosis.append(["lesson.diag.leaked", [row["name"], len(row["leaked"]), row["accounts"]]])
        elif outcome(row) == "inconclusive":
            diagnosis.append(["lesson.diag.inconclusive", [row["name"]]])
        elif outcome(row) == "blocked":
            diagnosis.append(["lesson.diag.benign_blocked", [row["name"], row["status"]]])
    passed = bool(rows) and all(outcome(row) in ("held", "served") for row in rows)
    return passed, diagnosis

def read_from(of: str, messages: list[dict]) -> list[str]:
    found = set()
    for message in messages:
        details = message.get("details") or {}
        rule = str(details.get("ruleId") or "")
        if not rule or rule.startswith(CRS_TOTALS):
            continue
        named = rule if of == "rule" else variable(details)
        if named:
            found.add(named)
    return sorted(found)

def variable(details: dict) -> str | None:
    for text in (details.get("match") or "", details.get("data") or ""):
        named = VARIABLE.search(str(text))
        if named:
            return next(group for group in named.groups() if group)
    return None

def level_refused(standing: dict, posture: dict) -> str | None:
    if [entry for entry in standing.get("exclusions") or [] if entry not in posture.get("exclusions", [])]:
        return "excluded"
    if (standing.get("paranoia") or CRS_DEFAULT_LEVEL) >= posture["paranoia"]:
        return "unchanged"
    return None

def unsolved(waf: dict | None, wanted: dict) -> list:
    if not waf:
        return [["lesson.diag.unread", []]]
    added = [entry for entry in waf.get("exclusions") or [] if entry not in wanted.get("exclusions", [])]
    level = waf.get("paranoia") or CRS_DEFAULT_LEVEL
    return ([["lesson.diag.excluded", [len(added)]]] if added else []) + (
        [["lesson.diag.level_low", [level]]] if level < wanted["paranoia"] else [])

def added_rules(live: str, baseline: str) -> list[int]:
    return sorted(suppress.sids(live) - suppress.sids(baseline))

def detection_outcome(row: dict) -> str:
    if row["malicious"]:
        if not row["alerts"]:
            return "missed"
        return "uncorroborated" if row["corroborated"] is False else "detected"
    return "alerted" if row["alerts"] else "quiet"

def scored(row: dict) -> str:
    if row["malicious"]:
        return "TP" if row["alerts"] else "FN"
    return "FP" if row["alerts"] else "TN"

def detection_verdict(rows: list[dict]) -> tuple[bool, list]:
    attacks = [row for row in rows if row["malicious"]]
    caught = [row for row in attacks if detection_outcome(row) == "detected"]
    diagnosis = [["lesson.diag.detected_ratio", [len(caught), len(attacks)]]]
    for row in rows:
        found = detection_outcome(row)
        if found == "uncorroborated":
            diagnosis.append(["lesson.diag.uncorroborated", [row["name"], row["expect"]]])
        elif found in ("missed", "alerted"):
            diagnosis.append([f"lesson.diag.{found}", [row["name"]]])
    passed = bool(rows) and all(detection_outcome(row) in ("detected", "quiet") for row in rows)
    return passed, diagnosis

def within(count: int, ratio: float) -> list[int]:
    if count <= 0:
        return []
    spread = max(2, round(count * ratio))
    return [count, *(found for found in range(max(1, count - spread), count + spread + 1) if found != count)]

def pasted_rows(text: str, parsed: list) -> list:
    return parsed or [found.groups() for found in map(PASTED_ROW.match, text.splitlines()) if found]
