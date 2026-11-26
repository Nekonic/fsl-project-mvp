from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

SIDES = ("attack", "defence")
ALL_CASES = "*"
STEP_LABEL = "bot_step.{}"
STANCE = ("This round's attack profile, for the defender's debrief, is {technique} {name} (MITRE ATT&CK: {quote}) "
          "It picks the kind of traffic the defender trains on; the scope and rules of engagement above bound every "
          "action.")


class Chooser(Protocol):
    def choice(self, seq: Sequence[str]) -> str: ...


@dataclass(frozen=True)
class Pace:
    per_window: int
    window_s: int
    min_gap_s: int


@dataclass(frozen=True)
class Allowance:
    operations: tuple[str, ...]
    cases: tuple[str, ...] = (ALL_CASES,)


@dataclass(frozen=True)
class Play:
    model: str
    pace: Pace
    allowance: Allowance
    budget_usd: float
    max_turns: int
    watch_s: int | None = None

    @property
    def family(self) -> str:
        parts = self.model.split("-")
        return parts[1] if len(parts) > 1 else self.model

    def shown(self) -> dict[str, Any]:
        return {"model": self.model, "family": self.family, "budget_usd": self.budget_usd,
                "max_turns": self.max_turns, "watch_s": self.watch_s,
                "pace": {"per_window": self.pace.per_window, "window_s": self.pace.window_s,
                         "min_gap_s": self.pace.min_gap_s},
                "allowance": {"operations": list(self.allowance.operations), "cases": list(self.allowance.cases)}}


@dataclass(frozen=True)
class Step:
    id: str
    attack: Play
    defence: Play

    @property
    def label(self) -> str:
        return STEP_LABEL.format(self.id)

    def play(self, side: str) -> Play:
        if side not in SIDES:
            raise ValueError(f"no side {side!r}")
        return self.attack if side == "attack" else self.defence


@dataclass(frozen=True)
class Card:
    id: str
    technique: str
    name: str
    quote: str
    url: str
    object_version: str
    release: str
    wargames: tuple[str, ...]

    def stance(self) -> str:
        return STANCE.format(technique=self.technique, name=self.name, quote=self.quote)

    def shown(self) -> dict[str, Any]:
        return {"id": self.id, "technique": self.technique, "name": self.name, "quote": self.quote, "url": self.url,
                "object_version": self.object_version, "release": self.release}


def draw_card(allowed: Sequence[str], rng: Chooser) -> str:
    if not allowed:
        raise ValueError("no card to draw from")
    return rng.choice(sorted(set(allowed)))


def pace_from(doc: Mapping) -> Pace:
    pace = Pace(per_window=int(doc["per_window"]), window_s=int(doc["window_s"]), min_gap_s=int(doc["min_gap_s"]))
    if pace.per_window < 1 or pace.window_s < 1 or pace.min_gap_s < 0:
        raise ValueError(f"pace {doc!r} is out of range")
    return pace


def play_from(doc: Mapping) -> Play:
    allowance = doc["allowance"]
    operations = tuple(str(name) for name in allowance["operations"])
    cases = tuple(str(name) for name in allowance.get("cases") or (ALL_CASES,))
    if not operations or not isinstance(doc["model"], str) or not doc["model"]:
        raise ValueError(f"play {doc!r} names no model or no operation")
    watch_s = None if doc.get("watch_s") is None else int(doc["watch_s"])
    if watch_s is not None and watch_s < 1:
        raise ValueError(f"watch_s {watch_s} is out of range")
    return Play(model=doc["model"], pace=pace_from(doc["pace"]), allowance=Allowance(operations, cases),
                budget_usd=float(doc["budget_usd"]), max_turns=int(doc["max_turns"]), watch_s=watch_s)


def steps_from(doc: Mapping) -> tuple[Step, ...]:
    steps = tuple(Step(id=str(one["id"]), attack=play_from(one["attack"]), defence=play_from(one["defence"]))
                  for one in doc["steps"])
    ids = [step.id for step in steps]
    if not steps or len(set(ids)) != len(ids):
        raise ValueError("steps are missing or name an id twice")
    return steps


def stand_ins_from(doc: Mapping, steps: Sequence[Step]) -> dict[str, str]:
    named = {side: str(doc["stand_in"][side]) for side in SIDES}
    known = {step.id for step in steps}
    if not set(named.values()) <= known:
        raise ValueError(f"stand-in steps {named} are not all steps")
    return named


def cards_from(doc: Mapping) -> tuple[Card, ...]:
    cards = tuple(Card(id=str(one["id"]), technique=str(one["technique"]), name=str(one["name"]),
                       quote=str(one["quote"]).strip(), url=str(one["url"]), object_version=str(one["object_version"]),
                       release=str(doc["release"]), wargames=tuple(str(name) for name in one["wargames"]))
                  for one in doc["cards"])
    ids = [card.id for card in cards]
    if len(set(ids)) != len(ids) or any(not card.quote or "," in card.technique for card in cards):
        raise ValueError("cards name an id twice, carry no quote or more than one technique")
    return cards
