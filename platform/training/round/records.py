from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from cr import errors
from domain import baseline as ranks
from domain.round_rules import Phase, human_side
from training.content import bots as catalog
from training.models import BotBaseline, Player, Round, RoundRecord
from training.round import bots as bot_runs
from training.round import debrief
from training.round import lifecycle

OTHER_SIDE = {"attack": "defence", "defence": "attack"}

logger = logging.getLogger(__name__)


def launcher_of(found: Round) -> dict:
    run = next((run for run in bot_runs.runs_of(found) if run.launcher), None)
    return dict(run.launcher) if run else {}


def profile_parts(snapshot: dict, side: str, step: str, launcher: dict) -> dict[str, Any]:
    opponent = OTHER_SIDE[side]
    return {"problem": ranks.problem_digest(snapshot), "human_side": side, "step": step,
            "opponent": catalog.play(step, opponent).shown(),
            "stand_in": catalog.play(catalog.stand_in(side), side).shown(),
            "cards": sorted((snapshot.get("round") or {}).get("cards") or []), "launcher": launcher}


def compared_as(found: Round) -> tuple[str, str] | None:
    if found.baseline_of_id is not None:
        return found.baseline_of.human_side, found.baseline_of.step
    side = human_side(found.matchup) if found.matchup != "pvp" else None
    bot = Player.objects.filter(round=found, side=OTHER_SIDE[side]).first() if side else None
    return (side, bot.step) if bot is not None and bot.step else None


def key_for(found: Round) -> str:
    compared = compared_as(found)
    if compared is None or not found.snapshot:
        return ""
    return ranks.profile_key(profile_parts(found.snapshot, *compared, launcher_of(found)))


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


def counts(found: Round, incomplete: bool, key: str) -> bool:
    if found.baseline_of_id is None or incomplete:
        return False
    if any(run.status == bot_runs.FAILED for run in bot_runs.runs_of(found)):
        return False
    held = found.baseline_of
    return not held.profile_key or held.profile_key == key


def take_sample(found: Round, score: dict, key: str) -> None:
    with transaction.atomic():
        held = BotBaseline.objects.get(pk=found.baseline_of_id)
        held.samples = [*held.samples, score["objectives"]["weighted"]]
        held.exits = dict(Counter(held.exits) + Counter(run.exit or "none" for run in bot_runs.runs_of(found)))
        if not held.profile_key:
            held.profile_key, held.launcher = key, launcher_of(found)
        held.save(update_fields=["samples", "exits", "profile_key", "launcher"])


def keep(found: Round) -> RoundRecord | None:
    if RoundRecord.objects.filter(round_number=found.pk).exists():
        return None
    incomplete = found.judged_at is None or not bot_runs.runs_over(found)
    players = {player.side: player for player in Player.objects.filter(round=found)}
    score = frozen(found, "the score", lambda one: lifecycle.shown_score(one, lifecycle.score(one)))
    key = key_for(found)
    counted = counts(found, incomplete, key) and score is not None
    try:
        with transaction.atomic():
            made = RoundRecord.objects.create(
                round_number=found.pk, problem_id=found.problem_id,
                problem_revision=(found.snapshot.get("problem") or {}).get("revision"), matchup=found.matchup,
                attack_user=getattr(players.get("attack"), "user", None),
                defence_user=getattr(players.get("defence"), "user", None),
                steps={side: player.step for side, player in players.items() if player.step},
                card=getattr(players.get("attack"), "card", ""), profile_key=key, started=found.started,
                ended=found.ended, end_reason=found.end_reason, score=score,
                debrief=frozen(found, "the debrief", debrief.compose) or {}, bot=bot_summary(found),
                baseline_id=found.baseline_of_id, counts_for_baseline=counted, incomplete=incomplete)
    except IntegrityError:
        return None
    if counted:
        take_sample(found, score, key)
    return made


def keep_when_due(found: Round) -> RoundRecord | None:
    return keep(found) if due(found) else None


def prune(now: datetime | None = None) -> int:
    cutoff = (now or timezone.now()) - timedelta(days=settings.RETAIN_RECORDS_DAYS)
    deleted, _ = RoundRecord.objects.filter(kept__lt=cutoff).delete()
    return deleted


def mine(user, problem_id: int | None = None) -> list[RoundRecord]:
    found = RoundRecord.objects.all()
    if not user.is_staff:
        found = found.filter(Q(attack_user=user) | Q(defence_user=user), baseline=None)
    if problem_id is not None:
        found = found.filter(problem_id=problem_id)
    return list(found[:200])


def record(record_id: int, user) -> RoundRecord:
    found = RoundRecord.objects.filter(pk=record_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_record")
    if not user.is_staff and user.pk not in (found.attack_user_id, found.defence_user_id):
        raise errors.NotAPlayer()
    return found


def standing_of(made: RoundRecord) -> dict[str, Any] | None:
    side = human_side(made.matchup) if made.baseline_id is None and made.matchup != "pvp" else None
    if side is None or not made.profile_key or not made.score:
        return None
    held = BotBaseline.objects.filter(status="current", profile_key=made.profile_key, human_side=side).last()
    if held is None:
        return None
    value = made.score["objectives"]["weighted"]
    return {"baseline": held.pk, "step": held.step, "n": len(held.samples),
            "top_percent": ranks.top_share(value, held.samples, side)}
