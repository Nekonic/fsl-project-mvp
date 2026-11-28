from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from cr.errors import Invalid, ServerError
from domain import bots
from domain.bots import Card, Play, Step

HERE = Path(__file__).resolve().parent
STEPS = HERE / "steps.yaml"
CARDS = HERE / "cards.yaml"


class BotCatalogBroken(ServerError):
    pass


def loaded(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@cache
def step_catalog() -> tuple[Step, ...]:
    doc = loaded(STEPS)
    try:
        return bots.steps_from(doc)
    except (KeyError, TypeError, ValueError) as broken:
        raise BotCatalogBroken(f"{STEPS} is malformed: {broken!r}") from broken


@cache
def card_catalog() -> tuple[tuple[Card, ...], str]:
    doc = loaded(CARDS)
    try:
        return bots.cards_from(doc), str(doc["notice"])
    except (KeyError, TypeError, ValueError) as broken:
        raise BotCatalogBroken(f"{CARDS} is malformed: {broken!r}") from broken


def steps() -> tuple[Step, ...]:
    return step_catalog()


def step_ids() -> frozenset[str]:
    return frozenset(step.id for step in steps())


def step(step_id: str) -> Step:
    found = next((one for one in steps() if one.id == step_id), None)
    if found is None:
        raise Invalid(code="unknown_step", path="step")
    return found


def play(step_id: str, side: str) -> Play:
    return step(step_id).play(side)


def cards() -> tuple[Card, ...]:
    return card_catalog()[0]


def notice() -> str:
    return card_catalog()[1]


def card_ids_for(wargame_id: str) -> frozenset[str]:
    return frozenset(card.id for card in cards() if wargame_id in card.wargames)


def card(card_id: str) -> Card | None:
    return next((one for one in cards() if one.id == card_id), None)
