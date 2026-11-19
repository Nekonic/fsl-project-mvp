from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from domain.checks import FACTS_NEEDED, AppliedRuleSet, Facts
from domain.types import ENGINES, ActionRecord, CommandRecord, DetectionRecord, ObjectiveRecord
from domain.verdicts import VerdictTable


@dataclass(frozen=True)
class Readers:
    latest_test: Callable[[str], VerdictTable | None]
    applied: Callable[[], tuple[AppliedRuleSet, ...]]
    detections: Callable[[], tuple[DetectionRecord, ...]]
    actions: Callable[[], tuple[ActionRecord, ...]]
    commands: Callable[[], tuple[CommandRecord, ...]]
    objectives: Callable[[], tuple[ObjectiveRecord, ...]]
    waf_before: Callable[[datetime | None], Mapping]
    waf_after: Callable[[], Mapping]


def latest_tests(readers: Readers) -> dict[str, VerdictTable]:
    return {engine: table for engine in ENGINES if (table := readers.latest_test(engine)) is not None}


READS: dict[str, Callable[[Readers, datetime | None], object]] = {
    "step_opened_at": lambda readers, opened_at: opened_at,
    "latest_tests": lambda readers, opened_at: latest_tests(readers),
    "applied": lambda readers, opened_at: readers.applied(),
    "detections": lambda readers, opened_at: readers.detections(),
    "actions": lambda readers, opened_at: readers.actions(),
    "commands": lambda readers, opened_at: readers.commands(),
    "objectives": lambda readers, opened_at: readers.objectives(),
    "waf_before": lambda readers, opened_at: readers.waf_before(opened_at),
    "waf_after": lambda readers, opened_at: readers.waf_after(),
}


def gather(kind: str, readers: Readers, opened_at: datetime | None) -> Facts:
    return Facts(**{name: READS[name](readers, opened_at) for name in FACTS_NEEDED[kind]})
