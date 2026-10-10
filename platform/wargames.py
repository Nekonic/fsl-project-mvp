from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from django.conf import settings

import lifecycle
from redteam.harness import is_tool_case, load_cases
from rules import crs

class UnknownWargame(KeyError):
    pass

class InvalidCatalogue(ValueError):
    pass

SCENARIO_FIELDS = ("name", "description", "image", "public_url", "objective_model", "case_file")
OBJECTIVE_MODELS = {"loot_verified", "effect_observed", "none"}
DIFFICULTIES = ("easy", "medium", "hard")
DEFAULT_DEFENSE = "full"
RULE_FILE = re.compile(r"[\w-]+\.rules", re.ASCII)

def checked_scenario(loaded: Any, wargame_id: str, source) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        raise InvalidCatalogue(f"{source}: a scenario is a mapping")
    missing = [
        field for field in SCENARIO_FIELDS
        if not isinstance(loaded.get(field), str) or not loaded[field].strip()
    ]
    if missing:
        raise InvalidCatalogue(
            f"{source}: a scenario needs a non-empty {', '.join(SCENARIO_FIELDS)}; "
            f"{', '.join(missing)} is missing or blank"
        )
    if loaded["objective_model"] not in OBJECTIVE_MODELS:
        raise InvalidCatalogue(
            f"{source}: objective_model {loaded['objective_model']!r} is not one of "
            f"{', '.join(sorted(OBJECTIVE_MODELS))}"
        )
    return {
        "id": wargame_id,
        **{field: loaded[field] for field in SCENARIO_FIELDS},
        **checked_card(loaded, source),
        **({"lesson": loaded["lesson"]} if "lesson" in loaded else {}),
        **({"defense": checked_defense(loaded["defense"], source)} if "defense" in loaded else {}),
    }

def checked_card(loaded: dict, source) -> dict[str, Any]:
    card = {field: loaded[field] for field in ("category", "difficulty", "minutes") if field in loaded}
    if "category" in card and not (isinstance(card["category"], str) and card["category"].strip()):
        raise InvalidCatalogue(f"{source}: category must be a non-empty name")
    if "difficulty" in card and card["difficulty"] not in DIFFICULTIES:
        raise InvalidCatalogue(f"{source}: difficulty must be one of {', '.join(DIFFICULTIES)}")
    minutes = card.get("minutes", 1)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise InvalidCatalogue(f"{source}: minutes must be a whole number above zero")
    return card

def checked_defense(declared: Any, source) -> dict[str, Any]:
    if not isinstance(declared, dict):
        raise InvalidCatalogue(f"{source}: defense maps a name to its waf and suricata")
    rules = Path(settings.FSL_SOURCE) / "deploy" / "suricata" / "rules"
    for name, posture in declared.items():
        posture = posture if isinstance(posture, dict) else {}
        try:
            crs.checked(posture.get("waf"))
        except crs.TuningRefused as exc:
            raise InvalidCatalogue(f"{source}: defense {name!r} waf: {exc}") from exc
        ruleset = posture.get("suricata")
        if not (isinstance(ruleset, str) and RULE_FILE.fullmatch(ruleset)
                and (rules / ruleset).is_file()):
            raise InvalidCatalogue(
                f"{source}: defense {name!r} suricata must name a file in "
                f"deploy/suricata/rules, got {ruleset!r}"
            )
    return declared

def checked_lesson(lesson: Any, known: set[str], source) -> None:
    if lesson is None:
        return
    cases = lesson.get("cases") if isinstance(lesson, dict) else None
    if not isinstance(lesson, dict) or not isinstance(lesson.get("text"), str) \
            or not isinstance(cases, list) or not cases:
        raise InvalidCatalogue(f"{source}: a lesson needs a text key and a non-empty cases list")
    unknown = sorted(str(name) for name in cases if name not in known)
    if unknown:
        raise InvalidCatalogue(f"{source}: lesson cases {', '.join(unknown)} are not in the case file")
    steps = lesson.get("steps", [])
    if not isinstance(steps, list) or not all(
        isinstance(step, dict) and isinstance(step.get("id"), str)
        and isinstance(step.get("command", ""), str) for step in steps
    ):
        raise InvalidCatalogue(f"{source}: lesson steps are a list of an id and an optional command")

def _discover() -> dict[str, dict[str, Any]]:
    root = Path(settings.FSL_SOURCE) / "wargames"
    found = {}
    for path in sorted(root.glob("*/scenario.yaml")):
        wargame_id = path.parent.name
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found[wargame_id] = checked_scenario(loaded, wargame_id, path)
        known = {
            case.get("name")
            for case in load_cases(Path(settings.WARGAME_CASES_DIR) / found[wargame_id]["case_file"])
        }
        checked_lesson(found[wargame_id].get("lesson"), known, path)
    return found

WARGAMES = _discover()

def objective_model(wargame_id: str) -> str:
    return WARGAMES[wargame_id]["objective_model"]

def defense(wargame_id: str, name: str) -> dict[str, Any] | None:
    declared = WARGAMES[wargame_id].get("defense") or {}
    if not declared and name == DEFAULT_DEFENSE:
        return None
    if name not in declared:
        raise UnknownWargame(name)
    return declared[name]

def lesson(wargame_id: str) -> dict[str, Any] | None:
    return WARGAMES[wargame_id].get("lesson")

def judged(wargame_id: str) -> bool:
    return objective_model(wargame_id) != "none"

def objectives(wargame_id: str) -> dict[str, Any]:
    if wargame_id not in WARGAMES:
        raise UnknownWargame(wargame_id)
    path = Path(settings.FSL_SOURCE) / "wargames" / wargame_id / "objectives.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return checked_objectives(loaded, path)

def checked_objectives(loaded: Any, source) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        raise InvalidCatalogue(f"{source}: an objective spec is a mapping")
    secret = loaded.get("secret")
    if not isinstance(secret, dict) or not secret.get("read_path"):
        raise InvalidCatalogue(f"{source}: secret.read_path is required")
    tiers = loaded.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        raise InvalidCatalogue(f"{source}: tiers must be a non-empty list")
    for tier in tiers:
        if not isinstance(tier, dict) or not isinstance(tier.get("key"), str) \
                or not isinstance(tier.get("difficulty"), int) \
                or not isinstance(tier.get("name"), str):
            raise InvalidCatalogue(
                f"{source}: each tier needs a key, a name, and an integer difficulty"
            )
    return loaded

def host(wargame_id: str) -> str:
    return urlsplit(WARGAMES[wargame_id]["public_url"]).netloc

def catalogue() -> list[dict[str, Any]]:
    return [_summarise(wargame) for wargame in WARGAMES.values()]

def cases(wargame_id: str) -> list[dict[str, Any]]:
    return [
        {
            "name": case["name"],
            "malicious": case["malicious"],
            "stage": case.get("stage") or "",
            "technique": case.get("technique") or "",
            "pattern": case.get("pattern") or "",
            "references": _references(case),
            "correlation": case.get("correlation") or "marker",
            "expect": case.get("expect") or "",
            "takes": case.get("takes") or "",
            "summary": _summary(case),
        }
        for case in _load(wargame_id)
    ]

def _references(case: dict[str, Any]) -> dict[str, str]:
    return {
        field: url
        for field in ("technique", "pattern")
        if (url := lifecycle.reference(case.get(field) or ""))
    }

def expectations(wargame_id: str) -> dict[str, str]:
    return {case["name"]: case.get("expect") or "" for case in _load(wargame_id)}

def find_case(wargame_id: str, name: str) -> dict[str, Any]:
    for case in _load(wargame_id):
        if case["name"] == name:
            return case
    raise UnknownWargame(name)

def _load(wargame_id: str) -> list[dict[str, Any]]:
    if wargame_id not in WARGAMES:
        raise UnknownWargame(wargame_id)
    path = Path(settings.WARGAME_CASES_DIR) / WARGAMES[wargame_id]["case_file"]
    return checked(load_cases(path), path)

def checked(loaded: Any, source) -> list[dict[str, Any]]:
    if not isinstance(loaded, list) or not all(isinstance(case, dict) for case in loaded):
        raise InvalidCatalogue(f"{source}: a catalogue is a list of cases")
    for case in loaded:
        name = case.get("name")
        if not isinstance(case.get("malicious"), bool):
            raise InvalidCatalogue(
                f"{source}: {name!r} must say malicious: true or false, "
                f"got {case.get('malicious')!r}"
            )
        if bool(case.get("request")) == bool(case.get("tool")):
            raise InvalidCatalogue(
                f"{source}: {name!r} must either send a request or run a tool, "
                f"and not both"
            )
    names = [case.get("name") for case in loaded]
    twice = sorted({str(name) for name in names if names.count(name) > 1})
    if twice:
        raise InvalidCatalogue(f"{source}: {', '.join(twice)} named more than once")
    return loaded

def _summarise(wargame: dict[str, Any]) -> dict[str, Any]:
    loaded = _load(wargame["id"])
    reached = {case.get("stage") for case in loaded}
    attacks = sum(1 for case in loaded if case["malicious"])
    return {
        "id": wargame["id"],
        "name": wargame["name"],
        "description": wargame["description"],
        "public_url": wargame["public_url"],
        "judged": wargame["objective_model"] != "none",
        "lesson": bool(wargame.get("lesson")),
        "model": wargame["objective_model"],
        "cases": len(loaded),
        "attacks": attacks,
        "benign": len(loaded) - attacks,
        "objectives": len(objectives(wargame["id"])["tiers"]) if wargame["objective_model"] != "none" else 0,
        "lesson_steps": len((wargame.get("lesson") or {}).get("steps") or []),
        "lesson_text": (wargame.get("lesson") or {}).get("text") or "",
        "category": wargame.get("category") or "",
        "difficulty": wargame.get("difficulty") or "",
        "minutes": wargame.get("minutes"),
        "covers": [stage for stage in lifecycle.STAGES if stage in reached],
        "uncovered": [stage for stage in lifecycle.STAGES if stage not in reached],
    }

def _summary(case: dict[str, Any]) -> str:
    if is_tool_case(case):
        return " ".join([case["tool"], *(case.get("args") or [])])
    request = case["request"]
    return f"{request.get('method', 'GET')} {request['path']}"
