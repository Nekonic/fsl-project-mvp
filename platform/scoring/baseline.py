from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

from cr import config, errors
from sandbox.runner import Runner
from scoring import effect, loot
from training.models import Round

LOOT_VERIFIED = "loot_verified"
EFFECT_OBSERVED = "effect_observed"
PLACEHOLDER = "*"

Reach = Callable[[str], Runner]


def objective_model(found: Round) -> str:
    return found.snapshot["wargame"]["objective_model"]


def secret(found: Round) -> Mapping[str, Any]:
    return found.snapshot["wargame"]["secret"]


def declared(found: Round) -> list[dict[str, Any]]:
    return list(found.snapshot.get("objectives") or [])


def tiers(found: Round) -> dict[str, list[dict[str, Any]]]:
    return {"tiers": [{"key": tier["key"], "name": tier["name"], "difficulty": tier["difficulty"], **tier["rule"]}
                      for tier in declared(found)]}


def ground_truth(wargame: Mapping[str, Any], reach: Reach | None = None) -> Any:
    held = wargame["secret"]
    if wargame["objective_model"] == LOOT_VERIFIED:
        inside = reach(held["role"]) if reach is not None else None
        return loot.baseline(dict(held), config.build().ground_truth, inside=inside)
    if reach is None:
        raise errors.Unavailable(code="ground_truth_unavailable")
    return effect.snapshot(reach(held["role"]))


def take_baseline(found: Round, reach: Reach | None = None) -> Any:
    baseline = ground_truth(found.snapshot["wargame"], reach)
    found.baseline = baseline
    found.save(update_fields=["baseline"])
    return baseline


def variants(value: str) -> set[str]:
    escaped = json.dumps(value)[1:-1]
    return {value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value), escaped,
            escaped.replace("/", "\\/")} - {""}


def redact(text: str, truth: Mapping[str, Any]) -> str:
    hidden = {variant for value in truth.values() if isinstance(value, str) and value for variant in variants(value)}
    for variant in sorted(hidden, key=len, reverse=True):
        text = text.replace(variant, PLACEHOLDER * len(variant))
    return text
