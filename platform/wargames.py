from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from django.conf import settings

import lifecycle
import traffic
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
CHECK_KINDS = {"click", "answer", "choice", "rules", "sent", "kali", "loot", "triage"}
TRIAGE_JUDGED = ("attack", "customer", "all")
TASK_CLASSES = ("judgement", "availability", "detection", "unknown")
GUIDANCE = ("worked", "faded", "none")
BRIEFING = ("situation", "goal", "measured_by")
CARD_MOMENTS = ("start", "alert", "blocked", "window")
COMPLETION = {"judgement": {"judged": ("all",)}, "availability": {"served": ("all",), "held": ("all",)},
              "detection": {"detected_by": ("suricata",)}, "unknown": {"served": ("all",), "held": ("all",)}}
COMPLETION_OPTIONS = {"judgement": ("pattern",), "availability": ("thresholds",)}
PATTERN_JUDGED = "judged"
REDS = ("schedule", "person")
SCENARIO_ID = re.compile(r"[0-9]+(\.[0-9]+)+", re.ASCII)
ANSWERS_OF = ("rule",)
RANGE_FACTS = ("entry", "logs", "segment", "lost", "excluded")
REQUEST_FACTS = ("status", "method", "path", "parameter", "status_class", "engine", "sensor_source", "waf_source",
                 "stopped_at")
KALI_FACTS = ("requests", "leaked")
DETECTORS = ("suricata",)
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
    if loaded["objective_model"] not in OBJECTIVE_MODELS:
        raise InvalidCatalogue(
            f"{source}: objective_model {loaded['objective_model']!r} is not one of "
            f"{', '.join(sorted(OBJECTIVE_MODELS))}"
        )
    return {
        "id": wargame_id,
        **{field: loaded[field] for field in SCENARIO_FIELDS},
        **checked_card(loaded, source),
        **({"foundations": loaded["foundations"]} if "foundations" in loaded else {}),
        **({"scenarios": loaded["scenarios"]} if "scenarios" in loaded else {}),
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
        checked_lesson_judging(taught, source)

def checked_groups(scenario: dict, source) -> None:
    ids = [taught["id"] for group in ("foundations", "scenarios") for taught in scenario.get(group) or []]
    twice = sorted({found for found in ids if ids.count(found) > 1})
    if twice:
        raise InvalidCatalogue(f"{source}: {', '.join(twice)} is declared twice among the foundations and scenarios")

def checked_scenarios(declared: Any, known: dict[str, bool], source, defenses, profiles) -> None:
    if declared is None:
        return
    if not isinstance(declared, list) or not declared or not all(isinstance(one, dict) for one in declared):
        raise InvalidCatalogue(f"{source}: scenarios is a non-empty list of scenarios")
    ids = [one.get("id") for one in declared]
    if not all(isinstance(found, str) and SCENARIO_ID.fullmatch(found) for found in ids) or len(set(ids)) != len(ids):
        raise InvalidCatalogue(f"{source}: every scenario needs its own id such as 1.1, got {ids}")
    orders = [one.get("order") for one in declared]
    if not all(type(order) is int for order in orders) or len(set(orders)) != len(orders):
        raise InvalidCatalogue(f"{source}: every scenario needs its own whole-number order, got {orders}")
    for one in declared:
        checked_scenario_run(one, known, f"{source}: scenario {one['id']}", defenses, profiles)
        if one.get("steps") is not None:
            if one["guidance"] != "worked":
                raise InvalidCatalogue(f"{source}: scenario {one['id']} has steps, which only a worked scenario takes")
            checked_lesson(as_lesson(one), set(known), source, defenses)
            checked_lesson_judging(as_lesson(one), source)

def checked_scenario_run(one: dict, known: dict[str, bool], where: str, defenses, profiles) -> None:
    for field, allowed in (("task_class", TASK_CLASSES), ("guidance", GUIDANCE)):
        if one.get(field) not in allowed:
            raise InvalidCatalogue(f"{where}: {field} must be one of {', '.join(allowed)}, got {one.get(field)!r}")
    if not (isinstance(one.get("text"), str) and one["text"].strip()):
        raise InvalidCatalogue(f"{where}: text must name the scenario's strings")
    briefing = one.get("briefing")
    if not isinstance(briefing, dict) or set(briefing) != set(BRIEFING) or not all(
            isinstance(key, str) and key.strip() for key in briefing.values()):
        raise InvalidCatalogue(f"{where}: briefing maps {', '.join(BRIEFING)} to string keys")
    minutes, window = one.get("minutes"), one.get("window_minutes")
    if not all(type(value) is int and value >= 1 for value in (minutes, window)) or window >= minutes:
        raise InvalidCatalogue(f"{where}: minutes and window_minutes are whole minutes, the window shorter")
    if one.get("defense") not in defenses:
        raise InvalidCatalogue(f"{where}: defense must be one the wargame declares, {', '.join(defenses)}")
    shaped = one.get("traffic")
    try:
        traffic.rate_of((shaped or {}).get("rate"))
    except ValueError as exc:
        raise InvalidCatalogue(f"{where}: traffic {exc}") from exc
    if not isinstance(shaped, dict) or shaped.get("profile") not in profiles:
        raise InvalidCatalogue(f"{where}: traffic.profile must be one of the wargame's customer profiles "
                               f"{sorted(profiles)}")
    red = one.get("red", REDS[0])
    if red not in REDS:
        raise InvalidCatalogue(f"{where}: red must be one of {', '.join(REDS)}, got {red!r}")
    checked_attacks(one.get("attacks"), known, minutes, where, red == "person")
    completion = one.get("completion")
    wanted = COMPLETION[one["task_class"]]
    optional = COMPLETION_OPTIONS.get(one["task_class"], ())
    if not isinstance(completion, dict) or set(completion) - set(optional) != set(wanted) or any(
            completion[key] not in allowed for key, allowed in wanted.items()):
        raise InvalidCatalogue(f"{where}: a {one['task_class']} scenario's completion is "
                               f"{ {key: list(allowed) for key, allowed in wanted.items()} }, optionally "
                               f"{', '.join(optional) or 'nothing else'}")
    checked_completion_options(completion, where)
    cards = one.get("cards", [])
    if not isinstance(cards, list) or not all(isinstance(card, dict) and isinstance(card.get("id"), str)
                                              and card.get("when") in CARD_MOMENTS for card in cards):
        raise InvalidCatalogue(f"{where}: cards are a list of an id and a when, one of {', '.join(CARD_MOMENTS)}")
    hints = one.get("hints", [])
    if not isinstance(hints, list) or not all(isinstance(hint, str) for hint in hints) or len(set(hints)) != len(hints):
        raise InvalidCatalogue(f"{where}: hints are a list of distinct hint ids")

def checked_completion_options(completion: dict, where: str) -> None:
    if "pattern" in completion and completion["pattern"] != PATTERN_JUDGED:
        raise InvalidCatalogue(f"{where}: completion.pattern can only be {PATTERN_JUDGED!r}")
    thresholds = completion.get("thresholds", {"inbound": 1})
    if not isinstance(thresholds, dict) or not thresholds or not set(thresholds) <= set(crs.THRESHOLDS) or not all(
            type(score) is int and 1 <= score <= crs.HIGHEST_THRESHOLD for score in thresholds.values()):
        raise InvalidCatalogue(f"{where}: completion.thresholds maps inbound and outbound to the highest anomaly "
                               f"threshold the final check accepts")

def checked_attacks(attacks: Any, known: dict[str, bool], minutes: int, where: str, by_person: bool = False) -> None:
    if by_person and attacks in (None, []):
        return
    if not isinstance(attacks, list) or not attacks:
        raise InvalidCatalogue(f"{where}: attacks is a non-empty list of an at, a case and an optional origin, "
                               f"unless red is person")
    for attack in attacks:
        attack = attack if isinstance(attack, dict) else {}
        at, case, origin = attack.get("at"), attack.get("case"), attack.get("origin", "")
        if type(at) is not int or not 0 <= at < minutes * 60:
            raise InvalidCatalogue(f"{where}: an attack's at is whole seconds after open within the scenario's "
                                   f"{minutes} minutes, got {at!r}")
        if not known.get(case):
            raise InvalidCatalogue(f"{where}: an attack's case must be a malicious case of the case file, got {case!r}")
        if not isinstance(origin, str):
            raise InvalidCatalogue(f"{where}: an attack's origin names an origin, got {origin!r}")

def as_lesson(one: dict) -> dict:
    detector = (one.get("completion") or {}).get("detected_by")
    return one | {"cases": list(dict.fromkeys(attack["case"] for attack in one.get("attacks") or [])),
                  "group": "scenarios", **({"detected_by": detector} if detector else {})}

def checked_lesson_judging(taught: dict, source) -> None:
    where = f"{source}: lesson {taught['id']}"
    if taught.get("detected_by") is not None and taught["detected_by"] not in DETECTORS:
        raise InvalidCatalogue(f"{where} detected_by must be one of {', '.join(DETECTORS)}")
    for step in taught.get("steps", []):
        checked_step_judging(taught, step, f"{where} step {step['id']}")

def _kinds_of_steps(taught: dict) -> dict[str, str]:
    return {step["id"]: step["check"]["kind"] for step in taught.get("steps", [])}

def read_from_record(taught: dict, check: dict) -> bool:
    of, about = check.get("of"), _kinds_of_steps(taught).get(check.get("about"))
    return (of in ANSWERS_OF and isinstance(check.get("path"), str) and bool(check["path"])) \
        or of in RANGE_FACTS or (of in REQUEST_FACTS and about == "sent") or (of in KALI_FACTS and about == "kali")

def checked_step_judging(taught: dict, step: dict, where: str) -> None:
    check = step["check"]
    kind = check["kind"]
    if kind in ("answer", "choice") and "of" in check and not read_from_record(taught, check):
        raise InvalidCatalogue(f"{where}: an answer read from the record needs of: one of "
                               f"{', '.join(ANSWERS_OF)} and the path of the request it is about, one of "
                               f"{', '.join(RANGE_FACTS)}, one of {', '.join(REQUEST_FACTS)} about a sent step, "
                               f"or one of {', '.join(KALI_FACTS)} about a kali step")
    if kind == "sent" and not _pattern(check.get("match")):
        raise InvalidCatalogue(f"{where}: a sent step needs match:, a regular expression for the request's URL")
    if kind == "loot" and _kinds_of_steps(taught).get(check.get("about")) != "kali":
        raise InvalidCatalogue(f"{where}: a loot step needs about: naming the kali step whose dump it takes")
    if kind in ("answer", "choice") and "of" not in check and not (
            isinstance(check.get("accept"), list) and check["accept"]):
        raise InvalidCatalogue(f"{where}: an answer needs an accept list, or of: to read it from the record")
    if kind == "rules" and not (taught.get("detected_by") and isinstance(step.get("rule"), str) and step["rule"].strip()):
        raise InvalidCatalogue(f"{where}: a rules step needs a lesson detected_by and the rule it applies when done for "
                               f"the learner")
    if kind == "triage" and check.get("judged") not in TRIAGE_JUDGED:
        raise InvalidCatalogue(f"{where}: a triage step needs judged:, one of {', '.join(TRIAGE_JUDGED)}")

def _pattern(given: Any) -> bool:
    if not isinstance(given, str) or not given:
        return False
    try:
        re.compile(given)
    except re.error:
        return False
    return True

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
    unarmed = [step["id"] for step in steps if step["check"]["kind"] == "kali" and step["check"].get("case") not in known]
    if unarmed:
        raise InvalidCatalogue(f"{source}: kali steps {', '.join(unarmed)} need case:, a tool case of the case file")

def _discover() -> dict[str, dict[str, Any]]:
    root = Path(settings.FSL_SOURCE) / "wargames"
    found = {}
    for path in sorted(root.glob("*/scenario.yaml")):
        wargame_id = path.parent.name
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found[wargame_id] = checked_scenario(loaded, wargame_id, path)
        malicious = {
            case.get("name"): case.get("malicious") is True
            for case in load_cases(Path(settings.WARGAME_CASES_DIR) / found[wargame_id]["case_file"])
        }
        known = set(malicious)
        defenses = tuple(found[wargame_id].get("defense") or (DEFAULT_DEFENSE,))
        checked_lessons(found[wargame_id].get("foundations"), known, path, defenses)
        checked_scenarios(found[wargame_id].get("scenarios"), malicious, path, defenses, _profiles(path.parent))
        checked_groups(found[wargame_id], path)
    return found

def _profiles(directory: Path) -> set[str]:
    declared = directory / "traffic.yaml"
    if not declared.exists():
        return set()
    return set(traffic.checked(yaml.safe_load(declared.read_text(encoding="utf-8")), declared)["profiles"])

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

def foundations(wargame_id: str) -> list[dict[str, Any]]:
    return sorted(WARGAMES[wargame_id].get("foundations") or [], key=lambda taught: taught["order"])

def scenarios(wargame_id: str) -> list[dict[str, Any]]:
    return sorted(WARGAMES[wargame_id].get("scenarios") or [], key=lambda one: one["order"])

def scenario_owner(scenario_id: Any) -> str | None:
    return next((wargame_id for wargame_id in WARGAMES
                 if any(one["id"] == scenario_id for one in scenarios(wargame_id))), None)

def scenario_run(scenario_id: str) -> dict[str, Any]:
    owner = scenario_owner(scenario_id)
    if owner is None:
        raise UnknownWargame(scenario_id)
    return next(one for one in scenarios(owner) if one["id"] == scenario_id)

def stepped_scenarios(wargame_id: str) -> list[dict[str, Any]]:
    return [as_lesson(one) for one in scenarios(wargame_id) if one.get("steps") is not None]

def taught_ids(wargame_id: str) -> list[str]:
    return [taught["id"] for taught in foundations(wargame_id)]

def lesson(wargame_id: str, waf: crs.Layout | None = None, *, lesson_id: str | None) -> dict[str, Any]:
    taught = next((taught for taught in foundations(wargame_id) + stepped_scenarios(wargame_id)
                   if taught["id"] == lesson_id), None)
    if taught is None:
        raise UnknownWargame(lesson_id)
    waf = waf or settings.FSL_WAF
    grouped = {"group": "foundations"} if taught in foundations(wargame_id) else {}
    return taught | grouped | {"steps": [
        step | {"command": step["command"].replace("{waf_rules}", waf.rules)} if step.get("command") else step
        for step in taught.get("steps", [])
    ]}

def lesson_defense(wargame_id: str, lesson_id: str) -> str:
    return lesson(wargame_id, lesson_id=lesson_id).get("defense", DEFAULT_DEFENSE)

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
        "model": wargame["objective_model"],
        "cases": len(loaded),
        "attacks": attacks,
        "benign": len(loaded) - attacks,
        "objectives": len(objectives(wargame["id"])["tiers"]) if wargame["objective_model"] != "none" else 0,
        "foundations": [_foundation_card(taught) for taught in foundations(wargame["id"])],
        "scenarios": [scenario_card(one) for one in scenarios(wargame["id"])],
        "category": wargame.get("category") or "",
        "difficulty": wargame.get("difficulty") or "",
        "minutes": wargame.get("minutes"),
        "covers": [stage for stage in lifecycle.STAGES if stage in reached],
        "uncovered": [stage for stage in lifecycle.STAGES if stage not in reached],
    }

def _foundation_card(taught: dict[str, Any]) -> dict[str, Any]:
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
        "learns": f"{taught['text']}.learns",
    }

def scenario_card(one: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": one["id"],
        "order": one["order"],
        "task_class": one["task_class"],
        "guidance": one["guidance"],
        "minutes": one["minutes"],
        "window_minutes": one["window_minutes"],
        "title": f"{one['text']}.title",
        "practise": f"{one['text']}.practise",
        "briefing": dict(one["briefing"]),
        "defense": one["defense"],
        "steps": len(one.get("steps") or []),
        "hints": len(one.get("hints") or []),
        "red": one.get("red", REDS[0]),
        "patterns": scenario_patterns(one),
    }

def scenario_patterns(one: dict[str, Any]) -> list[str]:
    if "pattern" not in one.get("completion", {}):
        return []
    owner = scenario_owner(one["id"])
    return sorted({case["pattern"] for case in cases(owner) if case["malicious"] and case["pattern"]}) if owner else []

def _summary(case: dict[str, Any]) -> str:
    if is_tool_case(case):
        return " ".join([case["tool"], *(case.get("args") or [])])
    request = case["request"]
    return f"{request.get('method', 'GET')} {request['path']}"
