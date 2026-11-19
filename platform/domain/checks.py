from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from domain.types import (
    ENGINES,
    TN,
    TP,
    ActionRecord,
    CommandRecord,
    DetectionRecord,
    FieldError,
    ObjectiveRecord,
)
from domain.verdicts import VerdictTable

PASSED, NOT_YET = "passed", "not_yet"

NORMALISE_TEXT, NORMALISE_NUMBER, NORMALISE_ORDER = "text", "number", "order"
WAF_FIELDS = ("paranoia", "thresholds", "exclusions", "detection_only")
WAF_CHANGES = {
    "paranoia": ("raised", "lowered"),
    "thresholds": ("raised", "lowered"),
    "exclusions": ("added", "removed", "narrowed"),
    "detection_only": ("on", "off"),
}
CRS_DEFAULT_LEVEL = 1
CRS_THRESHOLDS = {"inbound": 5, "outbound": 4}

GROUPED_NUMBER = re.compile(r"\d{1,3}(,\d{3})+")
COUNTED = re.compile(r"\s*([\d,]+)\s*[^\W\d_]{1,2}\s*")
ORDER_SEPARATOR = re.compile(r"[\s,>→]+")

DETAIL_CODES = frozenset({
    "no_answer",
    "wrong_answer",
    "wrong_order",
    "wrong_choice",
    "objective_kept",
    "no_test",
    "case_untested",
    "case_not_detected",
    "not_corroborated",
    "benign_alerted",
    "not_applied",
    "not_same_as_tested",
    "no_alert",
    "not_sent",
    "no_command",
    "waf_unchanged",
})


@dataclass(frozen=True)
class Param:
    kind: str
    required: bool = True
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    passed: bool
    detail_code: str | None = None

    @property
    def outcome(self) -> str:
        return PASSED if self.passed else NOT_YET


@dataclass(frozen=True)
class AppliedRuleSet:
    engine: str
    version: int
    applied_at: datetime
    same_as_tested: bool


@dataclass(frozen=True)
class Facts:
    step_opened_at: datetime | None = None
    latest_tests: Mapping[str, VerdictTable] = field(default_factory=dict)
    applied: tuple[AppliedRuleSet, ...] = ()
    detections: tuple[DetectionRecord, ...] = ()
    actions: tuple[ActionRecord, ...] = ()
    commands: tuple[CommandRecord, ...] = ()
    objectives: tuple[ObjectiveRecord, ...] = ()
    waf_before: Mapping | None = None
    waf_after: Mapping | None = None


STR, BOOL, STR_LIST, CHOICE = "str", "bool", "str_list", "choice"

CHECK_SCHEMAS: dict[str, dict[str, Param]] = {
    "answer": {
        "accept": Param(STR_LIST),
        "normalise": Param(CHOICE, required=False, choices=(NORMALISE_TEXT, NORMALISE_NUMBER, NORMALISE_ORDER)),
    },
    "choice": {"options": Param(STR_LIST), "correct": Param(STR)},
    "loot": {"objective": Param(STR)},
    "rule_test": {"engine": Param(CHOICE, choices=ENGINES), "case": Param(STR)},
    "rule_applied": {"engine": Param(CHOICE, choices=ENGINES), "same_as_tested": Param(BOOL)},
    "alert_seen": {
        "engine": Param(CHOICE, required=False, choices=ENGINES),
        "rule": Param(STR, required=False),
        "case": Param(STR, required=False),
    },
    "sent": {"method": Param(STR, required=False), "path_has": Param(STR)},
    "kali": {"command_has": Param(STR)},
    "waf_changed": {
        "field": Param(CHOICE, choices=WAF_FIELDS),
        "change": Param(CHOICE, choices=tuple(sorted({c for cs in WAF_CHANGES.values() for c in cs}))),
    },
}

FACTS_NEEDED: dict[str, tuple[str, ...]] = {
    "answer": (),
    "choice": (),
    "loot": ("objectives",),
    "rule_test": ("latest_tests",),
    "rule_applied": ("step_opened_at", "applied"),
    "alert_seen": ("detections",),
    "sent": ("step_opened_at", "actions"),
    "kali": ("step_opened_at", "commands"),
    "waf_changed": ("waf_before", "waf_after"),
}


def check_params(kind: object, params: object, path: str) -> list[FieldError]:
    if kind not in CHECK_SCHEMAS:
        return [FieldError(f"{path}.kind", "unknown_check")]
    if not isinstance(params, Mapping):
        return [FieldError(f"{path}.params", "not_an_object")]
    schema = CHECK_SCHEMAS[kind]
    errors = [FieldError(f"{path}.params.{name}", "unknown_field") for name in params if name not in schema]
    for name, param in schema.items():
        where = f"{path}.params.{name}"
        if name not in params:
            if param.required:
                errors.append(FieldError(where, "required"))
            continue
        errors.extend(_typed(params[name], param, where))
    if not errors:
        errors.extend(_coherent(kind, params, path))
    return errors


def _typed(value: object, param: Param, where: str) -> list[FieldError]:
    if param.kind == BOOL and type(value) is not bool:
        return [FieldError(where, "not_a_boolean")]
    if param.kind in (STR, CHOICE) and (not isinstance(value, str) or not value.strip()):
        return [FieldError(where, "not_a_text")]
    if param.kind == CHOICE and value not in param.choices:
        return [FieldError(where, "not_a_choice", (("choices", param.choices),))]
    if param.kind == STR_LIST and (
        not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value)
    ):
        return [FieldError(where, "not_a_text_list")]
    return []


def _coherent(kind: str, params: Mapping, path: str) -> list[FieldError]:
    if kind == "choice" and params["correct"] not in params["options"]:
        return [FieldError(f"{path}.params.correct", "not_an_option")]
    if kind == "waf_changed" and params["change"] not in WAF_CHANGES[params["field"]]:
        return [FieldError(f"{path}.params.change", "not_a_choice", (("choices", WAF_CHANGES[params["field"]]),))]
    return []


def judge_answer(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    if not isinstance(answer, str) or not answer.strip():
        return Verdict(False, "no_answer")
    accepted = [_bare(str(value)) for value in spec["accept"]]
    mode = spec.get("normalise", NORMALISE_TEXT)
    if mode == NORMALISE_ORDER:
        named = [_bare(name) for name in ORDER_SEPARATOR.split(answer) if name]
        if named == accepted:
            return Verdict(True)
        return Verdict(False, "wrong_order" if sorted(named) == sorted(accepted) else "wrong_answer")
    given = {_bare(answer)}
    if mode == NORMALISE_NUMBER:
        given |= {_bare(_ungrouped(answer)), _bare(_ungrouped(_unit_dropped(answer)))}
    return Verdict(True) if given & set(accepted) else Verdict(False, "wrong_answer")


def judge_choice(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    if answer is None:
        return Verdict(False, "no_answer")
    return Verdict(True) if answer == spec["correct"] else Verdict(False, "wrong_choice")


def judge_loot(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    lost = any(o.key == spec["objective"] and o.lost and o.by_loot for o in facts.objectives)
    return Verdict(True) if lost else Verdict(False, "objective_kept")


def judge_rule_test(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    latest = facts.latest_tests.get(spec["engine"])
    if latest is None:
        return Verdict(False, "no_test")
    row = latest.verdict_of(spec["case"])
    if row is None:
        return Verdict(False, "case_untested")
    if row.verdict != TP:
        return Verdict(False, "case_not_detected")
    if row.corroborated is False:
        return Verdict(False, "not_corroborated")
    if any(not other.malicious and other.verdict != TN for other in latest.cases):
        return Verdict(False, "benign_alerted")
    return Verdict(True)


def judge_rule_applied(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    applied = [
        one for one in facts.applied
        if one.engine == spec["engine"] and _since_opened(one.applied_at, facts)
    ]
    if not applied:
        return Verdict(False, "not_applied")
    if spec["same_as_tested"] and not any(one.same_as_tested for one in applied):
        return Verdict(False, "not_same_as_tested")
    return Verdict(True)


def judge_alert_seen(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    seen = any(
        (not spec.get("engine") or d.engine == spec["engine"])
        and (not spec.get("rule") or d.rule == spec["rule"])
        and (not spec.get("case") or d.marker == spec["case"])
        for d in facts.detections
    )
    return Verdict(True) if seen else Verdict(False, "no_alert")


def judge_sent(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    method = (spec.get("method") or "").upper()
    sent = any(
        _since_opened(action.started_at, facts)
        and (not method or (action.method or "").upper() == method)
        and spec["path_has"] in (action.path or "")
        for action in facts.actions
    )
    return Verdict(True) if sent else Verdict(False, "not_sent")


def judge_kali(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    ran = any(_since_opened(c.at, facts) and spec["command_has"] in c.line for c in facts.commands)
    return Verdict(True) if ran else Verdict(False, "no_command")


def judge_waf_changed(spec: Mapping, answer: object, facts: Facts) -> Verdict:
    changed = waf_changes(facts.waf_before or {}, facts.waf_after or {})
    return Verdict(True) if spec["change"] in changed.get(spec["field"], ()) else Verdict(False, "waf_unchanged")


def waf_changes(before: Mapping, after: Mapping) -> dict[str, tuple[str, ...]]:
    changes: dict[str, tuple[str, ...]] = {}
    level_before = before.get("paranoia") or CRS_DEFAULT_LEVEL
    level_after = after.get("paranoia") or CRS_DEFAULT_LEVEL
    changes["paranoia"] = _direction(level_before, level_after)
    moved = [_direction(_threshold(before, way), _threshold(after, way)) for way in CRS_THRESHOLDS]
    changes["thresholds"] = tuple(sorted({d for one in moved for d in one}))
    diff = exclusions_changed(list(before.get("exclusions") or []), list(after.get("exclusions") or []))
    changes["exclusions"] = tuple(
        name for name, present in (
            ("added", diff["added"]),
            ("removed", diff["removed"]),
            ("narrowed", [e for e in diff["added"] if e.get("target") and e.get("path")]),
        ) if present
    )
    was_on, now_on = bool(before.get("detection_only")), bool(after.get("detection_only"))
    changes["detection_only"] = ("on",) if now_on and not was_on else ("off",) if was_on and not now_on else ()
    return changes


def exclusions_changed(before: list, after: list) -> dict[str, list]:
    return {
        "added": [entry for entry in after if entry not in before],
        "removed": [entry for entry in before if entry not in after],
    }


JUDGES: dict[str, Callable[[Mapping, object, Facts], Verdict]] = {
    "answer": judge_answer,
    "choice": judge_choice,
    "loot": judge_loot,
    "rule_test": judge_rule_test,
    "rule_applied": judge_rule_applied,
    "alert_seen": judge_alert_seen,
    "sent": judge_sent,
    "kali": judge_kali,
    "waf_changed": judge_waf_changed,
}


def judge(kind: str, spec: Mapping, answer: object, facts: Facts) -> Verdict:
    return JUDGES[kind](spec, answer, facts)


def _direction(before: int, after: int) -> tuple[str, ...]:
    return ("raised",) if after > before else ("lowered",) if after < before else ()


def _threshold(tuning: Mapping, way: str) -> int:
    return (tuning.get("thresholds") or {}).get(way, CRS_THRESHOLDS[way])


def _since_opened(at: datetime, facts: Facts) -> bool:
    return facts.step_opened_at is None or at >= facts.step_opened_at


def _unit_dropped(text: str) -> str:
    found = COUNTED.fullmatch(text)
    return found[1] if found else text


def _ungrouped(text: str) -> str:
    return text.replace(",", "") if GROUPED_NUMBER.fullmatch(text.strip()) else text


def _bare(text: str) -> str:
    return "".join(text.split()).casefold()
