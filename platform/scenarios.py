from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from django.utils.dateparse import parse_datetime

DUE = "due"
FIRING = "firing"
FIRED = "fired"
FAILED = "failed"
CANCELLED = "cancelled"
SETTLED = (FIRED, FAILED, CANCELLED)
LEAKED = "leaked"
HELD = "held"
ATTACK = "attack"
CUSTOMER = "customer"
VERDICTS = (ATTACK, CUSTOMER)
WRONGS_BEFORE_OFFER = 2
IDLE = timedelta(minutes=5)

def at(value: str) -> datetime:
    return parse_datetime(value)

def schedule(declared: dict, opened_at: datetime) -> list[dict]:
    ordered = sorted(declared["attacks"], key=lambda attack: attack["at"])
    return [
        {"n": n, "case": attack["case"], "origin": attack.get("origin") or "", "at": attack["at"],
         "due": (opened_at + timedelta(seconds=attack["at"])).isoformat(), "state": DUE, "in_window": False}
        for n, attack in enumerate(ordered)
    ]

def ends_at(declared: dict, opened_at: datetime) -> datetime:
    return opened_at + timedelta(minutes=declared["minutes"])

def scheduled_window(declared: dict, opened_at: datetime) -> datetime:
    return ends_at(declared, opened_at) - timedelta(minutes=declared["window_minutes"])

def inside(entries: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [entry for entry in entries if start <= at(entry["due"]) < end]

def window_attacks(declared: dict, entries: list[dict], start: datetime, opened_at: datetime) -> list[dict]:
    end = start + timedelta(minutes=declared["window_minutes"])
    already = {entry["case"] for entry in inside(entries, start, end) if entry["state"] != CANCELLED}
    origins: dict[str, str] = {}
    for attack in sorted(declared["attacks"], key=lambda attack: attack["at"]):
        origins.setdefault(attack["case"], attack.get("origin") or "")
    missing = [case for case in origins if case not in already]
    gap = (end - start) / (len(missing) + 1)
    return [
        {"n": len(entries) + index, "case": case, "origin": origins[case],
         "at": round((start + gap * (index + 1) - opened_at).total_seconds()),
         "due": (start + gap * (index + 1)).isoformat(), "state": DUE, "in_window": True}
        for index, case in enumerate(missing)
    ]

def due_now(entries: list[dict], now: datetime) -> list[dict]:
    return [entry for entry in entries if entry["state"] == DUE and at(entry["due"]) <= now]

def ready_to_judge(entries: list[dict], window: dict, now: datetime) -> bool:
    start, end = at(window["started_at"]), at(window["ends_at"])
    return now >= end and all(entry["state"] in SETTLED for entry in inside(entries, start, end))

def judged_window(entries: list[dict], window: dict, blocked: int, extra: list, completion: dict) -> dict:
    attacks = [entry for entry in inside(entries, at(window["started_at"]), at(window["ends_at"]))
               if entry["state"] != CANCELLED]
    leaked = [entry for entry in attacks if entry.get("outcome") == LEAKED]
    unfired = [entry for entry in attacks if entry["state"] != FIRED]
    held = "held" in completion
    reasons = (
        ([["scenario.fail.blocked", [blocked]]] if blocked and "served" in completion else [])
        + ([["scenario.fail.leaked", [len(leaked), len(attacks)]]] if leaked and held else [])
        + ([["scenario.fail.unfired", [len(unfired)]]] if unfired and (held or "detected_by" in completion) else [])
        + extra
    )
    return {"passed": not reasons, "reasons": reasons, "attacks": len(attacks),
            "held": sum(1 for entry in attacks if entry.get("outcome") == HELD), "customers_blocked": blocked}

def judged_items(items: list[str], triage: dict) -> list:
    right = sum(1 for item in items if (triage.get(item) or {}).get("right"))
    return [] if right == len(items) else [["scenario.fail.judged", [right, len(items)]]]

def item_id(secret: str, marker: str) -> str:
    return hashlib.sha256(f"{secret}|{marker}".encode()).hexdigest()[:16]

def judged(truth: dict, verdict: str, succeeded) -> dict:
    wanted = ATTACK if truth["malicious"] else CUSTOMER
    verdict_right = verdict == wanted
    succeeded_right = None if verdict == CUSTOMER else succeeded is truth["succeeded"]
    return {"right": verdict_right and succeeded_right is not False,
            "verdict_right": verdict_right, "succeeded_right": succeeded_right}

def kept_judgement(kept: dict | None, verdict: str, succeeded, result: dict, now: str) -> dict:
    kept = dict(kept or {})
    tries = kept.get("tries", 0) + 1
    wrong = 0 if result["right"] else kept.get("wrong", 0) + 1
    return {"verdict": verdict, "succeeded": succeeded if verdict == ATTACK else None, "right": result["right"],
            "tries": tries, "wrong": wrong, "first_right": kept.get("first_right", result["right"] and tries == 1),
            "at": now}

def stuck_on_triage(kept: dict) -> bool:
    return kept["wrong"] >= WRONGS_BEFORE_OFFER

def idle(now: datetime, last_change: datetime, blocked_recently: int) -> bool:
    return now - last_change >= IDLE and blocked_recently > 0

def cards_due(cards: list[dict], alerts: int, blocked: int, window_started: bool) -> list[str]:
    reached = {"start": True, "alert": alerts > 0, "blocked": blocked > 0, "window": window_started}
    return [card["id"] for card in cards if reached[card["when"]]]

def phase(state: dict, closed: bool) -> str:
    if closed:
        return "closed"
    windows = state.get("windows") or []
    if windows and windows[-1].get("result") is None:
        return "window"
    if windows:
        return "passed" if windows[-1]["result"]["passed"] else "failed"
    return "running"

def version_of(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode()).hexdigest()[:16]
