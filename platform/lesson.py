from __future__ import annotations

def served(status: int) -> bool:
    return 200 <= status < 300

def verdict(rows: list[dict]) -> tuple[bool, list]:
    attacks = [row for row in rows if row["malicious"]]
    benign = [row for row in rows if not row["malicious"]]
    held = [row for row in attacks if not row["leaked"]]
    diagnosis = [["lesson.diag.blocked_ratio", [len(held), len(attacks)]]]
    diagnosis += [
        ["lesson.diag.leaked", [row["name"], len(row["leaked"]), row["accounts"]]]
        for row in attacks if row["leaked"]
    ]
    diagnosis += [
        ["lesson.diag.benign_blocked", [row["name"], row["status"]]]
        for row in benign if not served(row["status"])
    ]
    passed = bool(rows) and len(held) == len(attacks) and all(served(row["status"]) for row in benign)
    return passed, diagnosis
