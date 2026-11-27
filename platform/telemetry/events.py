from __future__ import annotations

from dataclasses import dataclass, field

from telemetry.models import Event

ATTACK = "attack"
DEFENCE = "defence"
STAFF = "staff"
OPERATOR = "operator"
SIDES = frozenset({ATTACK, DEFENCE})

BOTH = frozenset({ATTACK, DEFENCE, STAFF, OPERATOR})
ATTACK_SIDE = frozenset({ATTACK, STAFF})
DEFENCE_SIDE = frozenset({DEFENCE, STAFF})

TEXT = (str,)
NUMBER = (int,)
FLAG = (bool,)
MAYBE_TEXT = (str, type(None))
MAYBE_NUMBER = (int, type(None))
MAYBE_FLAG = (bool, type(None))


@dataclass(frozen=True)
class Kind:
    fields: dict[str, tuple[type, ...]]
    visible_to: frozenset[str]
    staff_fields: dict[str, tuple[type, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Viewer:
    sides: frozenset[str] = frozenset()
    staff: bool = False
    operator: bool = False

    @property
    def audiences(self) -> frozenset[str]:
        return self.sides | ({STAFF} if self.staff else set()) | ({OPERATOR} if self.operator else set())


KINDS: dict[str, Kind] = {
    "round.started": Kind({"ends_at": MAYBE_TEXT}, BOTH),
    "round.ended": Kind({"reason": TEXT}, BOTH),
    "round.judged": Kind({}, BOTH),
    "player.joined": Kind({"side": TEXT, "client": TEXT}, BOTH),
    "action.sent": Kind({"action": NUMBER, "kind": TEXT, "status": MAYBE_NUMBER}, ATTACK_SIDE),
    "tool.started": Kind({"run": NUMBER, "tool": TEXT}, ATTACK_SIDE),
    "tool.ended": Kind({"run": NUMBER, "exit_code": MAYBE_NUMBER, "stopped_by": MAYBE_TEXT}, ATTACK_SIDE),
    "command.run": Kind({"command": TEXT}, ATTACK_SIDE),
    "origin.spent": Kind({"ip": TEXT, "by": TEXT}, ATTACK_SIDE),
    "origin.switched": Kind({"ip": TEXT}, ATTACK_SIDE),
    "origins.spent": Kind({}, ATTACK_SIDE),
    "alert.seen": Kind({"alert": NUMBER, "engine": TEXT, "signature": TEXT}, DEFENCE_SIDE),
    "rule.tested": Kind({"test": NUMBER, "engine": TEXT, "ok": FLAG, "passed": FLAG}, DEFENCE_SIDE),
    "rule.applied": Kind({"engine": TEXT, "version": NUMBER, "source": TEXT}, DEFENCE_SIDE),
    "rule.refused": Kind({"engine": TEXT, "version": NUMBER, "message": TEXT}, DEFENCE_SIDE),
    "limit.below_floor": Kind({"zone": TEXT, "rate_rpm": NUMBER, "floor_rpm": NUMBER}, DEFENCE_SIDE),
    "limit.shared_key": Kind({"zone": TEXT}, DEFENCE_SIDE),
    "case.judged": Kind({"action": TEXT, "case": TEXT, "title": MAYBE_TEXT, "verdict": TEXT, "alerts": NUMBER, "corroborated": MAYBE_FLAG},
                        DEFENCE_SIDE),
    "objective.lost": Kind({"key": TEXT, "name": TEXT}, BOTH, staff_fields={"attributed_marker": MAYBE_TEXT}),
}


def visible_kinds(viewer: Viewer) -> list[str]:
    return sorted(name for name, kind in KINDS.items() if kind.visible_to & viewer.audiences)


def matches(value: object, types: tuple[type, ...]) -> bool:
    if isinstance(value, bool) and bool not in types:
        return False
    return isinstance(value, types)


def malformed(name: str, body: dict) -> list[str]:
    kind = KINDS[name]
    allowed = {**kind.fields, **kind.staff_fields}
    problems = [f"missing {key}" for key in kind.fields if key not in body]
    problems += [f"unknown {key}" for key in body if key not in allowed]
    problems += [f"{key} is {type(value).__name__}" for key, value in body.items()
                 if key in allowed and not matches(value, allowed[key])]
    return problems


def shown_body(name: str, body: dict, viewer: Viewer) -> dict:
    if viewer.staff:
        return dict(body)
    return {key: value for key, value in body.items() if key not in KINDS[name].staff_fields}


PAGE = 200



@dataclass(frozen=True)
class Page:
    events: list[dict]
    next: int


def append(round_id: int, kind: str, body: dict | None = None, player_side: str | None = None) -> Event:
    if kind not in KINDS:
        raise LookupError(f"no event kind {kind!r}")
    if player_side is not None and player_side not in SIDES:
        raise TypeError(f"player_side {player_side!r} is not a side")
    given = dict(body or {})
    problems = malformed(kind, given)
    if problems:
        raise TypeError(f"{kind} body: {', '.join(problems)}")
    return Event.objects.create(round_id=round_id, kind=kind, player_side=player_side, body=given)


def forget(round_ids: list[int]) -> int:
    deleted, _ = Event.objects.filter(round_id__in=list(round_ids)).delete()
    return deleted


def shown(event: Event, viewer: Viewer) -> dict:
    return {"id": event.id, "kind": event.kind, "at": event.at, "player_side": event.player_side,
            "body": shown_body(event.kind, event.body, viewer)}


def after(round_id: int, cursor: int, viewer: Viewer, limit: int = PAGE) -> Page:
    found = list(Event.objects.filter(round_id=round_id, id__gt=cursor, kind__in=visible_kinds(viewer))
                 .order_by("id")[:limit])
    return Page(events=[shown(event, viewer) for event in found], next=found[-1].id if found else cursor)
