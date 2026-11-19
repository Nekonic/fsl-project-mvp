from __future__ import annotations

import hashlib
import json
from datetime import datetime

from cr.config import WafConfig
from defence.models import RuleSet
from domain.types import ENGINE_WAF
from events import log
from range.runner import Runner
from rules import crs

DEFENCE = "defence"


def head_posture(round_id: int) -> RuleSet | None:
    return RuleSet.objects.filter(round_id=round_id, engine=ENGINE_WAF).order_by("-version").first()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def drifted(head: RuleSet, gateway: Runner, config: WafConfig) -> bool:
    live = crs.read(gateway, config)["file"]
    return digest(live) != digest(crs.rendered(crs.checked(json.loads(head.body))))


def check(round_id: int, gateway: Runner, config: WafConfig, now: datetime) -> bool:
    head = head_posture(round_id)
    if head is None:
        return False
    try:
        moved = drifted(head, gateway, config)
    except crs.WafUnreadable:
        return False
    if not moved:
        return False
    if head.drifted_at is None:
        head.drifted_at = now
        head.save(update_fields=["drifted_at"])
        log.append(round_id, "rule.drifted", {"engine": ENGINE_WAF}, seat_side=DEFENCE)
    return True


def any_drift(round_id: int) -> bool:
    return RuleSet.objects.filter(round_id=round_id, engine=ENGINE_WAF, drifted_at__isnull=False).exists()
