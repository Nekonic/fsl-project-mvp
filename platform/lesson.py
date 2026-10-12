from __future__ import annotations

DO_IT = 4
WRONGS_PER_HINT = 2
CRS_DEFAULT_LEVEL = 1

def answered(check: dict, given: str, wrong: str) -> tuple[bool, list | None]:
    if given in check.get("accept", []):
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
