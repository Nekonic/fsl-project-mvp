from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from domain.types import ACTION_ORIGIN_REQUEST, ActionRecord, DetectionRecord
from telemetry import alerts as alert_feed
from telemetry import events as log
from training.content import bots as catalog
from training.models import Action, Player, Round
from training.round import bots as bot_runs
from training.round import lifecycle

ATTACK, DEFENCE, BOTH = "attack", "defence", "both"
ATTACK_KINDS = ("tool.started", "tool.ended", "command.run", "origin.spent", "origin.switched")
DEFENCE_KINDS = ("rule.tested", "rule.applied", "rule.refused", "case.judged")
SHARED_KINDS = frozenset(name for name, kind in log.KINDS.items()
                         if kind.visible_to == log.BOTH and not name.startswith(("round.", "player.")))
TIMELINE_KINDS = frozenset(ATTACK_KINDS) | frozenset(DEFENCE_KINDS) | SHARED_KINDS
BOTH_SIDES = log.Viewer(sides=log.SIDES)
BENIGN_VERDICTS = ("tn", "fp")
SHOWN_NOTES = frozenset({"text", "result"})
KOREAN = re.compile("[\uac00-\ud7a3]")
EMPHASIS = re.compile(r"\*\*|__|`")
HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")


def when(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def events_of(found: Round) -> list[dict]:
    return log.every(found.pk, BOTH_SIDES, TIMELINE_KINDS)


def action_rows(found: Round, free_alerts: dict[str, int], seen: Sequence[DetectionRecord],
                requests: Sequence[ActionRecord]) -> list[dict]:
    alerted = Counter(detection.marker for detection in seen if detection.marker)
    rows, free = [], defaultdict(list)
    for action in Action.objects.filter(round=found).order_by("started", "id"):
        if action.case_id:
            rows.append({"lane": ATTACK, "kind": "case", "at": when(action.started), "case": action.case_id,
                         "origin": action.source_ip, "alerts": alerted[action.marker]})
        else:
            free[action.source_ip or ""].append((action.started, action.ended))
    for request in sorted(requests, key=lambda record: record.started_at):
        free[request.source_ip or ""].append((request.started_at, request.ended_at))
    for origin, actions in free.items():
        actions.sort(key=lambda action: action[0])
        rows.append({"lane": ATTACK, "kind": "free_actions", "at": when(actions[0][0]), "origin": origin or None,
                     "count": len(actions), "until": when(max(action[1] or action[0] for action in actions)),
                     "alerts": free_alerts.get(origin, 0)})
    return rows


def free_alerts_of(score: dict) -> dict[str, int]:
    return {origin["ip"]: origin["alerts"] for origin in score["free_actions"]["by_origin"]}


def alert_rows(seen: Sequence[DetectionRecord]) -> list[dict]:
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for detection in seen:
        grouped[(detection.engine, detection.rule or detection.signature)].append(detection)
    rows = []
    for (engine, _), seen in grouped.items():
        first = min(seen, key=lambda one: one.timestamp)
        rows.append({"lane": DEFENCE, "kind": "alerts", "at": when(first.timestamp), "engine": engine,
                     "rule": first.rule, "signature": first.signature, "count": len(seen),
                     "until": when(max(one.timestamp for one in seen))})
    return rows


def fired_at(event: dict, fired: dict[str, datetime], end: datetime | None) -> datetime:
    if event["kind"] == "case.judged" and event["body"].get("action") in fired:
        return fired[event["body"]["action"]]
    return min(event["at"], end) if end else event["at"]


def event_rows(found: Round) -> list[dict]:
    fired = {record.action_id: record.started_at for record in lifecycle.logged_actions(found)}
    end = found.ended or found.ends_at
    rows, benign = [], {}
    for event in events_of(found):
        lane = ATTACK if event["kind"] in ATTACK_KINDS else DEFENCE if event["kind"] in DEFENCE_KINDS else None
        if event["kind"] in SHARED_KINDS:
            lane = BOTH
        if lane is None:
            continue
        at = fired_at(event, fired, end)
        verdict = event["body"].get("verdict") if event["kind"] == "case.judged" else None
        if verdict not in BENIGN_VERDICTS:
            rows.append({"lane": lane, "kind": event["kind"], "at": when(at), **event["body"]})
            continue
        held = benign.setdefault((event["body"]["case"], verdict), {
            "lane": lane, "kind": event["kind"], "at": when(at), **event["body"], "alerts": 0, "count": 0, "until": when(at)})
        held["count"] += 1
        held["alerts"] += event["body"].get("alerts") or 0
        held["at"], held["until"] = min(held["at"], when(at)), max(held["until"], when(at))
    return rows + list(benign.values())


def plain(text: str) -> str:
    return HEADING.sub("", EMPHASIS.sub("", text)).strip()


def shown_note(kind: str, text: str) -> str | None:
    if kind not in SHOWN_NOTES or not KOREAN.search(text):
        return None
    return plain(text) or None


def note_rows(found: Round) -> list[dict]:
    rows = [{"lane": note.run.player.side, "kind": "bot_note", "at": when(note.at), "note": note.kind,
             "text": shown_note(note.kind, note.text)} for note in bot_runs.notes_of(found)]
    return [row for row in rows if row["text"]]


def cleaned(composed: dict[str, Any]) -> dict[str, Any]:
    timeline = []
    for row in composed.get("timeline") or []:
        if row.get("kind") != "bot_note":
            timeline.append(row)
        elif (text := shown_note(str(row.get("note")), str(row.get("text") or ""))) is not None:
            timeline.append({**row, "text": text})
    return {**composed, "timeline": timeline}


def bot_lines(found: Round) -> list[dict]:
    lines = []
    for run in bot_runs.runs_of(found):
        lines.append({"side": run.player.side, "step": run.player.step, "model": run.model, "status": run.status,
                      "exit": run.exit, "cost_usd": run.cost_usd, "turns": run.turns, "refusals": run.refusals,
                      "closing": run.closing, "finished": when(run.finished),
                      "left_of_round_s": bot_runs.left_of_round(run, found)})
    return lines


def card_of(found: Round) -> dict[str, Any] | None:
    attacker = Player.objects.filter(round=found, side=ATTACK).exclude(card="").first()
    card = catalog.card(attacker.card) if attacker else None
    return None if card is None else {**card.shown(), "notice": catalog.notice()}


def objective_marks(score: dict) -> list[dict]:
    return [{"key": one["key"], "name": one["name"], "detected": one["detected"], "responded": one["responded"],
             "response_seconds": one["response_seconds"]} for one in score["objectives"]["lost"]]


def compose(found: Round) -> dict[str, Any]:
    seen = alert_feed.detections(found)
    acted = tuple(lifecycle.actions(found))
    requests = [one for one in acted if one.kind == ACTION_ORIGIN_REQUEST]
    score = lifecycle.shown_score(found, lifecycle.score_over(found, acted, seen))
    titles = lifecycle.case_titles(found)
    timeline = (action_rows(found, free_alerts_of(score), seen, requests) + alert_rows(seen) + event_rows(found)
                + note_rows(found))
    timeline = [{**row, "title": titles.get(row["case"], row["case"])} if row.get("case") else row for row in timeline]
    timeline.sort(key=lambda row: row["at"] or "")
    return {
        "round": found.pk, "matchup": found.matchup, "pending": lifecycle.pending(found),
        "steps": {player.side: player.step or None for player in Player.objects.filter(round=found)},
        "card": card_of(found), "bots": bot_lines(found), "objectives": objective_marks(score),
        "timeline": timeline, "score": score,
    }
