from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from domain.scoring.correlate import WINDOW_SLACK
from telemetry import alerts as alert_feed
from telemetry import events as log
from training.content import bots as catalog
from training.attack import actions as attack
from training.models import Action, Player, Round
from training.round import bots as bot_runs
from training.round import lifecycle

ATTACK, DEFENCE, BOTH = "attack", "defence", "both"
ATTACK_KINDS = ("tool.started", "tool.ended", "command.run", "origin.spent", "origin.switched")
DEFENCE_KINDS = ("rule.tested", "rule.applied", "rule.refused", "case.judged")
SHARED_KINDS = frozenset(name for name, kind in log.KINDS.items()
                         if kind.visible_to == log.BOTH and not name.startswith(("round.", "player.")))
BOTH_SIDES = log.Viewer(sides=log.SIDES)


def when(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def events_of(found: Round) -> list[dict]:
    seen, cursor = [], 0
    while True:
        page = log.after(found.pk, cursor, BOTH_SIDES)
        seen += page.events
        if not page.events:
            return seen
        cursor = page.next


def action_rows(found: Round) -> list[dict]:
    detections = alert_feed.detections(found)
    alerted = Counter(detection.marker for detection in detections if detection.marker)
    rows, free = [], defaultdict(list)
    for action in Action.objects.filter(round=found).order_by("started", "id"):
        if action.case_id:
            rows.append({"lane": ATTACK, "kind": "case", "at": when(action.started), "case": action.case_id,
                         "origin": action.source_ip, "alerts": alerted[action.marker]})
        else:
            free[action.source_ip or ""].append((action.started, action.ended, alerted[action.marker]))
    for request in sorted(attack.origin_records(found), key=lambda record: record.started_at):
        free[request.source_ip or ""].append((request.started_at, request.ended_at, 0))
    for origin, actions in free.items():
        actions.sort(key=lambda action: action[0])
        rows.append({"lane": ATTACK, "kind": "free_actions", "at": when(actions[0][0]), "origin": origin or None,
                     "count": len(actions), "until": when(max(action[1] or action[0] for action in actions)),
                     "alerts": sum(action[2] for action in actions)
                     + origin_alerts(detections, origin, actions[0][0], actions[-1][0])})
    return rows


def origin_alerts(detections, origin: str, first: datetime, last: datetime) -> int:
    return sum(1 for detection in detections if origin and detection.src_ip == origin and detection.marker is None
               and first - WINDOW_SLACK <= detection.timestamp <= last + WINDOW_SLACK)


def alert_rows(found: Round) -> list[dict]:
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for detection in alert_feed.detections(found):
        grouped[(detection.engine, detection.signature)].append(detection)
    return [{"lane": DEFENCE, "kind": "alerts", "at": when(min(one.timestamp for one in seen)), "engine": engine,
             "signature": signature, "count": len(seen), "until": when(max(one.timestamp for one in seen))}
            for (engine, signature), seen in grouped.items()]


def event_rows(found: Round) -> list[dict]:
    rows = []
    for event in events_of(found):
        lane = ATTACK if event["kind"] in ATTACK_KINDS else DEFENCE if event["kind"] in DEFENCE_KINDS else None
        if event["kind"] in SHARED_KINDS:
            lane = BOTH
        if lane is not None:
            rows.append({"lane": lane, "kind": event["kind"], "at": when(event["at"]), **event["body"]})
    return rows


def note_rows(found: Round) -> list[dict]:
    return [{"lane": note.run.player.side, "kind": "bot_note", "at": when(note.at), "note": note.kind,
             "text": note.text} for note in bot_runs.notes_of(found)]


def bot_lines(found: Round) -> list[dict]:
    lines = []
    for run in bot_runs.runs_of(found):
        lines.append({"side": run.player.side, "step": run.player.step, "model": run.model, "status": run.status,
                      "exit": run.exit, "cost_usd": run.cost_usd, "turns": run.turns, "refusals": run.refusals,
                      "closing": run.closing})
    return lines


def card_of(found: Round) -> dict[str, Any] | None:
    attacker = Player.objects.filter(round=found, side=ATTACK).exclude(card="").first()
    card = catalog.card(attacker.card) if attacker else None
    return None if card is None else {**card.shown(), "notice": catalog.notice()}


def objective_marks(score: dict) -> list[dict]:
    return [{"key": one["key"], "name": one["name"], "detected": one["detected"], "responded": one["responded"],
             "response_seconds": one["response_seconds"]} for one in score["objectives"]["lost"]]


def compose(found: Round) -> dict[str, Any]:
    score = lifecycle.score(found).shown()
    timeline = action_rows(found) + alert_rows(found) + event_rows(found) + note_rows(found)
    timeline.sort(key=lambda row: row["at"] or "")
    return {
        "round": found.pk, "matchup": found.matchup, "pending": lifecycle.pending(found),
        "steps": {player.side: player.step or None for player in Player.objects.filter(round=found)},
        "card": card_of(found), "bots": bot_lines(found), "objectives": objective_marks(score),
        "timeline": timeline, "score": score,
    }
