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
CHECK_KINDS = {"alert", "click", "answer", "choice", "waf", "served", "replay", "verify"}
REPLAY_EXPECTS = ("held", "served")
RULE_FILE = re.compile(r"[\w-]+\.rules", re.ASCII)
LESSON_ID = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)

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
    if "lesson" in loaded:
        raise InvalidCatalogue(f"{source}: lessons are declared as a lessons: list, not a single lesson:")
    if loaded["objective_model"] not in OBJECTIVE_MODELS:
        raise InvalidCatalogue(
            f"{source}: objective_model {loaded['objective_model']!r} is not one of "
            f"{', '.join(sorted(OBJECTIVE_MODELS))}"
        )
    return {
        "id": wargame_id,
        **{field: loaded[field] for field in SCENARIO_FIELDS},
        **checked_card(loaded, source),
        **({"lessons": loaded["lessons"]} if "lessons" in loaded else {}),
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

def checked_lessons(lessons: Any, known: set[str], source, defenses=(DEFAULT_DEFENSE,)) -> None:
    if lessons is None:
        return
    if not isinstance(lessons, list) or not lessons or not all(isinstance(taught, dict) for taught in lessons):
        raise InvalidCatalogue(f"{source}: lessons is a non-empty list of lessons")
    ids = [taught.get("id") for taught in lessons]
    if not all(isinstance(found, str) and LESSON_ID.fullmatch(found) for found in ids) or len(set(ids)) != len(ids):
        raise InvalidCatalogue(f"{source}: every lesson needs its own id of lowercase letters, digits and dashes, got {ids}")
    orders = [taught.get("order") for taught in lessons]
    if not all(type(order) is int for order in orders) or len(set(orders)) != len(orders):
        raise InvalidCatalogue(f"{source}: every lesson needs its own whole-number order, got {orders}")
    for taught in lessons:
        checked_lesson_card(taught, set(ids) - {taught["id"]}, source)
        checked_lesson(taught, known, source, defenses)

def checked_lesson_card(taught: dict, others: set[str], source) -> None:
    if "level" in taught and taught["level"] not in DIFFICULTIES:
        raise InvalidCatalogue(f"{source}: lesson {taught['id']} level must be one of {', '.join(DIFFICULTIES)}")
    minutes = taught.get("minutes", 1)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise InvalidCatalogue(f"{source}: lesson {taught['id']} minutes must be a whole number above zero")
    needed = taught.get("prerequisites", [])
    if not isinstance(needed, list) or not set(needed) <= others:
        raise InvalidCatalogue(
            f"{source}: lesson {taught['id']} prerequisites must name other lessons of the scenario, got {needed!r}"
        )

def checked_lesson(lesson: Any, known: set[str], source, defenses=(DEFAULT_DEFENSE,)) -> None:
    cases = lesson.get("cases") if isinstance(lesson, dict) else None
    if not isinstance(lesson, dict) or not isinstance(lesson.get("text"), str) \
            or not isinstance(cases, list) or not cases:
        raise InvalidCatalogue(f"{source}: a lesson needs a text key and a non-empty cases list")
    if lesson.get("defense", DEFAULT_DEFENSE) not in defenses:
        raise InvalidCatalogue(
            f"{source}: the lesson's defense must be one the scenario declares, "
            f"{', '.join(defenses)}; got {lesson.get('defense')!r}"
        )
    unknown = sorted(str(name) for name in cases if name not in known)
    if unknown:
        raise InvalidCatalogue(f"{source}: lesson cases {', '.join(unknown)} are not in the case file")
    steps = lesson.get("steps", [])
    if not isinstance(steps, list) or not all(
        isinstance(step, dict) and isinstance(step.get("id"), str)
        and isinstance(step.get("command", ""), str) for step in steps
    ):
        raise InvalidCatalogue(f"{source}: lesson steps are a list of an id and an optional command")
    unchecked = [
        step["id"] for step in steps
        if not isinstance(step.get("check"), dict) or step["check"].get("kind") not in CHECK_KINDS
    ]
    if unchecked:
        raise InvalidCatalogue(
            f"{source}: lesson steps {', '.join(unchecked)} need a check whose kind is one of "
            f"{', '.join(sorted(CHECK_KINDS))}"
        )
    unreplayable = [
        step["id"] for step in steps if step["check"]["kind"] == "replay"
        and (step["check"].get("case") not in cases or step["check"].get("expect") not in REPLAY_EXPECTS)
    ]
    if unreplayable:
        raise InvalidCatalogue(
            f"{source}: replay steps {', '.join(unreplayable)} need a case of the lesson and an expect of "
            f"{', '.join(REPLAY_EXPECTS)}"
        )

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
        checked_lessons(found[wargame_id].get("lessons"), known, path,
                        tuple(found[wargame_id].get("defense") or (DEFAULT_DEFENSE,)))
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

def lessons(wargame_id: str) -> list[dict[str, Any]]:
    return sorted(WARGAMES[wargame_id].get("lessons") or [], key=lambda taught: taught["order"])

def lesson(wargame_id: str, waf: crs.Layout | None = None, *, lesson_id: str | None = None) -> dict[str, Any] | None:
    listed = lessons(wargame_id)
    if not listed:
        return None
    taught = next((taught for taught in listed if taught["id"] == lesson_id), None) if lesson_id else listed[0]
    if taught is None:
        raise UnknownWargame(lesson_id)
    waf = waf or settings.FSL_WAF
    return taught | {"steps": [
        step | {"command": step["command"].replace("{waf_rules}", waf.rules).replace("{waf_reload}", waf.reload)}
        if step.get("command") else step
        for step in taught.get("steps", [])
    ]}

def lesson_defense(wargame_id: str, lesson_id: str | None = None) -> str:
    return (lesson(wargame_id, lesson_id=lesson_id) or {}).get("defense", DEFAULT_DEFENSE)

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
    first = lesson(wargame["id"])
    return {
        "id": wargame["id"],
        "name": wargame["name"],
        "description": wargame["description"],
        "public_url": wargame["public_url"],
        "judged": wargame["objective_model"] != "none",
        "lesson": bool(wargame.get("lessons")),
        "model": wargame["objective_model"],
        "cases": len(loaded),
        "attacks": attacks,
        "benign": len(loaded) - attacks,
        "objectives": len(objectives(wargame["id"])["tiers"]) if wargame["objective_model"] != "none" else 0,
        "lesson_steps": len((first or {}).get("steps") or []),
        "lesson_text": (first or {}).get("text") or "",
        "lesson_defense": lesson_defense(wargame["id"]) if first else "",
        "lessons": [_lesson_card(taught) for taught in lessons(wargame["id"])],
        "category": wargame.get("category") or "",
        "difficulty": wargame.get("difficulty") or "",
        "minutes": wargame.get("minutes"),
        "covers": [stage for stage in lifecycle.STAGES if stage in reached],
        "uncovered": [stage for stage in lifecycle.STAGES if stage not in reached],
    }

def _lesson_card(taught: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": taught["id"],
        "order": taught["order"],
        "title": f"{taught['text']}.title",
        "goal": f"{taught['text']}.summary",
        "minutes": taught.get("minutes"),
        "level": taught.get("level") or "",
        "defense": taught.get("defense", DEFAULT_DEFENSE),
        "prerequisites": list(taught.get("prerequisites") or []),
        "steps": len(taught.get("steps") or []),
    }

def _summary(case: dict[str, Any]) -> str:
    if is_tool_case(case):
        return " ".join([case["tool"], *(case.get("args") or [])])
    request = case["request"]
    return f"{request.get('method', 'GET')} {request['path']}"
