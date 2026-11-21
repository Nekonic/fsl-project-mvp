from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from domain.types import ActionRecord, DetectionRecord
from testing import factories
from training.content import problems as content
from training.models import Allocation, Round, Player

ATTACKER_IP = "198.51.100.9"


def problem(wargame: str = "board", objectives: Sequence[str] = ()):
    document = factories.round_problem(objectives=list(objectives))
    document["problem"]["wargame"] = wargame
    return content.save_document(document)


def opened(found_problem, *, opened_by=None, phase: str = "running", started: datetime | None = None,
           ended: datetime | None = None) -> Round:
    now = datetime.now(timezone.utc)
    allocation = Allocation.objects.create(wargame_id=found_problem.wargame_id, purpose=found_problem.kind, slot=1,
                                 opened_by=opened_by, expires_at=now + timedelta(hours=1))
    return Round.objects.create(allocation=allocation, problem=found_problem, kind=found_problem.kind,
                                matchup="pvp", phase=phase,
                                snapshot=content.snapshot(found_problem), started=started or now, ended=ended)


def playing(found: Round, side: str, user=None, bot_name: str = "") -> Player:
    return Player.objects.create(round=found, side=side, client="human" if user else "bot", user=user,
                               bot_name=bot_name)


def action(marker: str, at: datetime, *, malicious: bool | None = None, kind: str = "request",
           case_id: str | None = None, expect: str | None = None, source_ip: str = ATTACKER_IP,
           seconds: float = 1.0, correlation: str = "marker") -> ActionRecord:
    return ActionRecord(action_id=marker, kind=kind, marker=marker, correlation=correlation, source_ip=source_ip,
                        started_at=at, ended_at=at + timedelta(seconds=seconds), case_id=case_id,
                        malicious=malicious, expect=expect)


def case(marker: str, at: datetime, *, malicious: bool, expect: str | None = None, **given) -> ActionRecord:
    return action(marker, at, malicious=malicious, kind="case", case_id=marker, expect=expect, **given)


def detection(detection_id: str, at: datetime, *, marker: str | None, signature: str = "",
              src_ip: str = ATTACKER_IP, blocked: bool = False) -> DetectionRecord:
    return DetectionRecord(detection_id=detection_id, timestamp=at, src_ip=src_ip, marker=marker, engine="ids",
                           rule="1", signature=signature, blocked=blocked)
