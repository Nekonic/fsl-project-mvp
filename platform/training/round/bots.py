from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from cr import errors
from domain.round_rules import BOT, Phase
from training.content import bots as catalog
from training.models import BotNote, BotRun, Player, Round
from users import players as player_tokens

QUEUED, RUNNING, FINISHED, FAILED = "queued", "running", "finished", "failed"
OVER = (FINISHED, FAILED)
FAILED_EXITS = frozenset({"launcher_restarted", "crashed", "round_ended", "timed_out"})
NOTE_TEXT_MAX = 2000
SIDE_PROMPTS = {"attack": "attacker", "defence": "defender"}


@dataclass(frozen=True)
class Claimed:
    run: int
    round: int
    side: str
    step: str
    token: str
    play: dict[str, Any]
    card: dict[str, Any] | None
    prompt: dict[str, Any]


def step_lines() -> list[dict[str, Any]]:
    return [{"id": step.id, "label": step.label, "attack": step.attack.shown(), "defence": step.defence.shown()}
            for step in catalog.steps()]


def launched(player: Player) -> bool:
    return player.client == BOT and bool(player.step)


def queue(found: Round) -> list[BotRun]:
    return [BotRun.objects.create(player=player, model=catalog.play(player.step, player.side).model)
            for player in Player.objects.filter(round=found, client=BOT).exclude(step="")]


def run_of(run_id: int) -> BotRun:
    found = BotRun.objects.select_related("player", "player__round").filter(pk=run_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_bot_run")
    return found


def runs_of(found: Round) -> list[BotRun]:
    return list(BotRun.objects.filter(player__round=found).select_related("player").order_by("id"))


def runs_over(found: Round) -> bool:
    return all(run.status in OVER for run in runs_of(found))


def latest_run(player: Player) -> BotRun | None:
    return BotRun.objects.filter(player=player).order_by("-id").first()


def fail(runs: Iterable[BotRun], exit_reason: str, at: datetime) -> None:
    for run in runs:
        BotRun.objects.filter(pk=run.pk).exclude(status__in=OVER).update(status=FAILED, exit=exit_reason,
                                                                       finished=at)
        player_tokens.revoke_token(run.player, at)


def stance_of(player: Player) -> dict[str, Any] | None:
    card = catalog.card(player.card) if player.card else None
    return None if card is None else {**card.shown(), "notice": catalog.notice(), "stance": card.stance()}


def claim(restarted: bool = False, launcher: Mapping | None = None) -> Claimed | None:
    at = timezone.now()
    if restarted:
        fail(BotRun.objects.filter(status=RUNNING).select_related("player"), "launcher_restarted", at)
    fail(BotRun.objects.filter(status=QUEUED, player__round__phase=Phase.ENDED.value).select_related("player"),
         "round_ended", at)
    for run in BotRun.objects.filter(status=QUEUED, player__round__phase=Phase.RUNNING.value).order_by("queued", "id"):
        with transaction.atomic():
            if not BotRun.objects.filter(pk=run.pk, status=QUEUED).update(status=RUNNING, claimed=at,
                                                                         launcher=dict(launcher or {})):
                continue
            player = Player.objects.select_related("round").get(pk=run.player_id)
            token = player_tokens.issue_token(player)
        card = stance_of(player) if player.side == "attack" else None
        return Claimed(run=run.pk, round=player.round_id, side=player.side, step=player.step, token=token,
                       play=catalog.play(player.step, player.side).shown(), card=card,
                       prompt={"side": SIDE_PROMPTS[player.side], "stance": card["stance"] if card else None})
    return None


def report(run: BotRun, notes: Iterable[Mapping]) -> int:
    made = [BotNote(run=run, at=note["at"], kind=note["kind"], text=str(note["text"])[:NOTE_TEXT_MAX])
            for note in notes]
    BotNote.objects.bulk_create(made)
    return len(made)


def finish(run: BotRun, exit_reason: str, cost_usd: float | None, turns: int | None, refusals: int,
           closing: str) -> BotRun:
    at = timezone.now()
    status = FAILED if exit_reason in FAILED_EXITS else FINISHED
    BotRun.objects.filter(pk=run.pk).exclude(status__in=OVER).update(
        status=status, exit=exit_reason, cost_usd=cost_usd, turns=turns, refusals=refusals,
        closing=closing[:NOTE_TEXT_MAX * 5], finished=at)
    player_tokens.revoke_token(run.player, at)
    run.refresh_from_db()
    return run


def notes_of(found: Round) -> list[BotNote]:
    return list(BotNote.objects.filter(run__player__round=found).select_related("run__player").order_by("at", "id"))
