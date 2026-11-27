from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from cr import errors
from domain.round_rules import Phase
from training.models import Player, Round, RoundRecord
from training.round import bots as bot_runs
from training.round import debrief
from training.round import lifecycle

logger = logging.getLogger(__name__)


def due(found: Round) -> bool:
    return (found.phase == Phase.ENDED.value and found.judged_at is not None and bot_runs.runs_over(found)
            and not RoundRecord.objects.filter(round_number=found.pk).exists())


def frozen(found: Round, what: str, make) -> Any:
    try:
        return make(found)
    except (errors.DomainError, OSError, LookupError, ValueError) as failed:
        logger.warning("round %s: %s was not kept: %s", found.pk, what, failed)
        return None


def bot_summary(found: Round) -> dict[str, dict]:
    return {run.player.side: {"exit": run.exit, "status": run.status, "cost_usd": run.cost_usd, "turns": run.turns,
                              "refusals": run.refusals, "model": run.model} for run in bot_runs.runs_of(found)}


def keep(found: Round) -> RoundRecord | None:
    if RoundRecord.objects.filter(round_number=found.pk).exists():
        return None
    incomplete = found.judged_at is None or not bot_runs.runs_over(found)
    players = {player.side: player for player in Player.objects.filter(round=found)}
    score = frozen(found, "the score", lambda one: lifecycle.shown_score(one, lifecycle.score(one)))
    try:
        with transaction.atomic():
            made = RoundRecord.objects.create(
                round_number=found.pk, wargame_id=found.allocation.wargame_id, problem_id=found.problem_id,
                problem_revision=(found.snapshot.get("problem") or {}).get("revision"), matchup=found.matchup,
                attack_user=getattr(players.get("attack"), "user", None),
                defence_user=getattr(players.get("defence"), "user", None),
                steps={side: player.step for side, player in players.items() if player.step},
                card=getattr(players.get("attack"), "card", ""), started=found.started,
                ended=found.ended, end_reason=found.end_reason, score=score,
                debrief=frozen(found, "the debrief", debrief.compose) or {}, bot=bot_summary(found),
                incomplete=incomplete)
    except IntegrityError:
        return None
    return made


def keep_when_due(found: Round) -> RoundRecord | None:
    return keep(found) if due(found) else None


def restate_bots(found: Round) -> None:
    for kept in RoundRecord.objects.filter(round_number=found.pk):
        kept.bot = bot_summary(found)
        if kept.debrief:
            kept.debrief = {**kept.debrief, "bots": debrief.bot_lines(found)}
        kept.save(update_fields=["bot", "debrief"])


def prune(now: datetime | None = None) -> int:
    cutoff = (now or timezone.now()) - timedelta(days=settings.RETAIN_RECORDS_DAYS)
    deleted, _ = RoundRecord.objects.filter(kept__lt=cutoff).delete()
    return deleted


LISTED_WITHOUT = ("score", "debrief", "bot")


def mine(user, problem_id: int | None = None) -> list[RoundRecord]:
    found = RoundRecord.objects.select_related("problem").defer(*LISTED_WITHOUT)
    found = found.filter(Q(attack_user=user) | Q(defence_user=user))
    found = found.filter(Q(problem=None) | Q(problem__published=True))
    if problem_id is not None:
        found = found.filter(problem_id=problem_id)
    return list(found[:200])


def record(record_id: int, user) -> RoundRecord:
    found = RoundRecord.objects.filter(pk=record_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_record")
    if not user.is_staff and user.pk not in (found.attack_user_id, found.defence_user_id):
        raise errors.NotAPlayer()
    if found.debrief:
        found.debrief = debrief.cleaned(found.debrief)
    return found


def kept_score(found: Round) -> dict | None:
    kept = RoundRecord.objects.filter(round_number=found.pk).exclude(score=None).values_list("score", flat=True).first()
    return kept or None
