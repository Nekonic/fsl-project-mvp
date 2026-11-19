from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from domain.checks import check_params
from domain.round_rules import ALLOWED_MATCHUPS, Matchup, Side
from domain.types import FieldError

KINDS = ("lesson", "round")
PANES = ("kibana", "terminal_kali", "terminal_waf", "site", "map", "ids_rules", "waf", "alerts", "none")
HP_FIELDS = ("budget", "per_request", "refused_x", "burst_per_s", "burst_x")
CASE_PARAMS = {"rule_test": "case", "alert_seen": "case"}
OBJECTIVE_PARAMS = {"loot": "objective"}


@dataclass(frozen=True)
class CatalogCase:
    malicious: bool
    recorded: bool = False
    tool_case: bool = False


@dataclass(frozen=True)
class WargameCatalog:
    cases: Mapping[str, CatalogCase] = field(default_factory=dict)
    objectives: frozenset[str] = frozenset()


def validate_problem(doc: object, catalog: Mapping[str, WargameCatalog]) -> list[FieldError]:
    if not isinstance(doc, Mapping):
        return [FieldError("", "not_an_object")]
    problem = doc.get("problem")
    if not isinstance(problem, Mapping):
        return [FieldError("problem", "required")]

    errors = _problem(problem, catalog)
    wargame = catalog.get(problem["wargame"]) if _named_in(problem.get("wargame"), catalog) else None
    side = problem.get("side")
    kind = problem.get("kind")

    steps = doc.get("steps", [])
    if not isinstance(steps, list):
        errors.append(FieldError("steps", "not_a_list"))
    else:
        if kind == "lesson" and not steps:
            errors.append(FieldError("steps", "required"))
        errors.extend(_steps(steps, wargame))

    setup = doc.get("round")
    if setup is None:
        if kind == "round":
            errors.append(FieldError("round", "required"))
    elif not isinstance(setup, Mapping):
        errors.append(FieldError("round", "not_an_object"))
    else:
        errors.extend(_round(setup, wargame, side))
    return errors


def _problem(problem: Mapping, catalog: Mapping[str, WargameCatalog]) -> list[FieldError]:
    errors = []
    if problem.get("kind") not in KINDS:
        errors.append(FieldError("problem.kind", "not_a_choice", (("choices", KINDS),)))
    if problem.get("side") not in tuple(Side):
        errors.append(FieldError("problem.side", "not_a_choice", (("choices", tuple(Side)),)))
    if not _named_in(problem.get("wargame"), catalog):
        errors.append(FieldError("problem.wargame", "unknown_wargame"))
    if not _text(problem.get("title")):
        errors.append(FieldError("problem.title", "required"))
    for name in ("summary", "body"):
        if name in problem and not isinstance(problem[name], str):
            errors.append(FieldError(f"problem.{name}", "not_a_text"))
    if "published" in problem and type(problem["published"]) is not bool:
        errors.append(FieldError("problem.published", "not_a_boolean"))
    return errors


def _steps(steps: list, wargame: WargameCatalog | None) -> list[FieldError]:
    errors = []
    for index, step in enumerate(steps):
        at = f"steps[{index}]"
        if not isinstance(step, Mapping):
            errors.append(FieldError(at, "not_an_object"))
            continue
        if step.get("order") != index + 1:
            errors.append(FieldError(f"{at}.order", "out_of_sequence", (("expected", index + 1),)))
        if not _text(step.get("body")):
            errors.append(FieldError(f"{at}.body", "required"))
        if step.get("opens", "none") not in PANES:
            errors.append(FieldError(f"{at}.opens", "unknown_pane"))
        hints = step.get("hints", [])
        if not isinstance(hints, list) or not all(_text(hint) for hint in hints):
            errors.append(FieldError(f"{at}.hints", "not_a_text_list"))
        errors.extend(_check(step.get("check"), f"{at}.check", wargame))
    return errors


def _check(check: object, at: str, wargame: WargameCatalog | None) -> list[FieldError]:
    if not isinstance(check, Mapping):
        return [FieldError(at, "required")]
    kind, params = check.get("kind"), check.get("params", {})
    errors = check_params(kind, params, at)
    if errors or wargame is None:
        return errors
    if (name := CASE_PARAMS.get(kind)) and params.get(name) and params[name] not in wargame.cases:
        errors.append(FieldError(f"{at}.params.{name}", "unknown_case"))
    if (name := OBJECTIVE_PARAMS.get(kind)) and params[name] not in wargame.objectives:
        errors.append(FieldError(f"{at}.params.{name}", "unknown_objective"))
    return errors


def _round(setup: Mapping, wargame: WargameCatalog | None, side: object) -> list[FieldError]:
    errors = []
    matchups = setup.get("matchups")
    if not isinstance(matchups, list) or not matchups:
        errors.append(FieldError("round.matchups", "required"))
    else:
        allowed = ALLOWED_MATCHUPS.get(side, frozenset()) if side in tuple(Side) else frozenset()
        for index, matchup in enumerate(matchups):
            at = f"round.matchups[{index}]"
            if matchup not in tuple(Matchup):
                errors.append(FieldError(at, "not_a_choice", (("choices", tuple(Matchup)),)))
            elif side in tuple(Side) and matchup not in allowed:
                errors.append(FieldError(at, "matchup_not_allowed", (("side", str(side)),)))

    errors.extend(_listed(setup, "probe_cases", wargame, _probe_case))
    errors.extend(_listed(setup, "objectives", wargame, _objective))

    hp = setup.get("hp")
    if not isinstance(hp, Mapping):
        errors.append(FieldError("round.hp", "required"))
    else:
        errors.extend(
            FieldError(f"round.hp.{name}", "not_a_positive_integer")
            for name in HP_FIELDS
            if not _positive(hp.get(name))
        )
    if "benign_every_s" in setup and not _positive(setup["benign_every_s"]):
        errors.append(FieldError("round.benign_every_s", "not_a_positive_integer"))
    if setup.get("time_limit_s") is not None and not _positive(setup["time_limit_s"]):
        errors.append(FieldError("round.time_limit_s", "not_a_positive_integer"))
    return errors


def _listed(setup: Mapping, name: str, wargame: WargameCatalog | None, each) -> list[FieldError]:
    values = setup.get(name, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return [FieldError(f"round.{name}", "not_a_text_list")]
    if wargame is None:
        return []
    return [
        FieldError(f"round.{name}[{index}]", code)
        for index, value in enumerate(values)
        if (code := each(value, wargame))
    ]


def _probe_case(case_id: str, wargame: WargameCatalog) -> str | None:
    case = wargame.cases.get(case_id)
    if case is None:
        return "unknown_case"
    if not case.malicious:
        return "not_malicious"
    if not case.recorded:
        return "not_recorded"
    return None


def _objective(key: str, wargame: WargameCatalog) -> str | None:
    return None if key in wargame.objectives else "unknown_objective"


def _named_in(value: object, names: Mapping) -> bool:
    return isinstance(value, str) and value in names


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
