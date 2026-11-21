from __future__ import annotations

from dataclasses import dataclass, field

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
    "seat.joined": Kind({"side": TEXT, "client": TEXT}, BOTH),
    "action.sent": Kind({"action": NUMBER, "kind": TEXT, "status": MAYBE_NUMBER}, ATTACK_SIDE),
    "tool.started": Kind({"run": NUMBER, "tool": TEXT}, ATTACK_SIDE),
    "tool.ended": Kind({"run": NUMBER, "exit_code": MAYBE_NUMBER, "stopped_by": MAYBE_TEXT}, ATTACK_SIDE),
    "command.run": Kind({"command": TEXT}, ATTACK_SIDE),
    "origin.charged": Kind({"ip": TEXT, "charged": NUMBER, "left": NUMBER}, ATTACK_SIDE),
    "origin.spent": Kind({"ip": TEXT}, ATTACK_SIDE),
    "origin.switched": Kind({"ip": TEXT}, ATTACK_SIDE),
    "origins.spent": Kind({}, ATTACK_SIDE),
    "alert.seen": Kind({"alert": NUMBER, "engine": TEXT, "signature": TEXT}, DEFENCE_SIDE),
    "rule.tested": Kind({"test": NUMBER, "engine": TEXT, "ok": FLAG}, DEFENCE_SIDE),
    "rule.applied": Kind({"engine": TEXT, "version": NUMBER}, DEFENCE_SIDE),
    "rule.disabled": Kind({"sid": NUMBER, "expires_at": TEXT}, DEFENCE_SIDE),
    "rule.drifted": Kind({"engine": TEXT}, DEFENCE_SIDE),
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
