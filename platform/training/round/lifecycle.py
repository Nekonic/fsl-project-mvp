from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cr import errors
from cr.config import configured
from domain import round_rules
from domain.round_rules import BOT, HUMAN, AllocationState, Matchup, Phase, RoundState
from sandbox import service as sandbox
from sandbox import topology
from sandbox.definitions import read as read_declaration
from sandbox.reach import slot_range
from scoring import baseline as baselines
from scoring import losses
from scoring import score as referee
from telemetry import alerts as alert_feed
from telemetry import events as log
from training.attack import actions as attack
from training.attack import origins
from training.content import probes
from training.content import problems as content
from training.defence import kibana_gate
from training.defence import rules as defence
from training.defence import terminal as defence_terminal
from training.models import Allocation, Round, Player
from training.round import access as auth
from training.round import site
from training.traffic import customers
from users import players as player_tokens

ROUND = "round"
SIDES = ("attack", "defence")
ENDED = Phase.ENDED.value
RUNNING = Phase.RUNNING.value
CREATED = Phase.CREATED.value
STARTING = Phase.STARTING.value

READ_ABANDONED = timedelta(minutes=5)
READER_POLL_SECONDS = 0.5

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Created:
    round: Round
    bot_tokens: dict[str, str]


def refuse_fallen(held: Allocation) -> None:
    if not round_rules.may_start_scored(AllocationState(objective_fallen=losses.fallen_on(held.pk))):
        raise errors.Conflict(code="objective_fallen")


def playing_user(given: Any, path: str):
    found = get_user_model().objects.filter(username=given, is_active=True).first() if isinstance(given, str) else None
    if found is None:
        raise errors.Invalid(code="unknown_account", path=f"{path}.username")
    return found


def player_of(found: Round, side: str, client: str, asked: dict) -> Player:
    path = f"players.{side}"
    if client == BOT:
        name = (asked.get("bot") or {}).get("name") if isinstance(asked.get("bot"), dict) else None
        if not isinstance(name, str) or not name.strip():
            raise errors.Invalid(code="invalid_choice", path=path)
        return Player.objects.create(round=found, side=side, client=BOT, bot_name=name.strip())
    if "username" in asked:
        return Player.objects.create(round=found, side=side, client=HUMAN, user=playing_user(asked["username"], path))
    if asked.get("open") is True:
        return Player.objects.create(round=found, side=side, client=HUMAN)
    raise errors.Invalid(code="invalid_choice", path=path)


def create_round(held: Allocation, problem_id: int, matchup: str, players: dict[str, dict]) -> Created:
    if held.closed is not None:
        raise errors.Conflict(code="allocation_closed")
    problem = content.problem(problem_id)
    if problem.wargame_id != held.wargame_id or problem.kind != ROUND:
        raise errors.Invalid(code="invalid_choice", path="problem")
    allowed = (content.snapshot(problem).get("round") or {}).get("matchups") or []
    if matchup not in allowed:
        raise errors.Invalid(code="matchup_not_allowed", path="matchup")
    if Round.objects.filter(allocation=held).exclude(phase=ENDED).exists():
        raise errors.Conflict(code="round_open")
    refuse_fallen(held)
    users = [asked.get("username") for asked in players.values() if isinstance(asked, dict) and asked.get("username")]
    if len(users) != len(set(users)):
        raise errors.Conflict(code="already_playing")
    tokens: dict[str, str] = {}
    with transaction.atomic():
        found = Round.objects.create(allocation=held, problem=problem, kind=ROUND, matchup=matchup)
        made = [player_of(found, side.value, client, dict(players.get(side.value) or {}))
                for side, client in round_rules.PLAYERS[Matchup(matchup)].items()]
        for player in made:
            if player.client == BOT:
                tokens[player.side] = player_tokens.issue_token(player)
    for player in made:
        if player.client == BOT or player.user_id is not None:
            log.append(found.pk, "player.joined", {"side": player.side, "client": player.client})
    return Created(round=found, bot_tokens=tokens)


def round_of(round_id: int) -> Round:
    found = Round.objects.select_related("allocation").filter(pk=round_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_round")
    return found


def players(found: Round) -> list[Player]:
    return list(Player.objects.filter(round=found).order_by("side"))


def rounds_for(user, mine: bool = False, state: str = "") -> list[Round]:
    found = Round.objects.select_related("allocation").order_by("-id")
    if mine or (state != "joinable" and not user.is_staff):
        found = found.filter(Q(players__user=user) | Q(allocation__opened_by=user)).distinct()
    if state == "open":
        found = found.exclude(phase=ENDED)
    elif state == "joinable":
        found = found.filter(phase=CREATED, kind=ROUND, players__client=HUMAN, players__user=None).distinct()
    return list(found[:100])


def join(found: Round, side: str, user) -> Player:
    if found.phase == ENDED:
        raise errors.Conflict(code="round_closed")
    player = Player.objects.filter(round=found, side=side).first()
    if player is None:
        raise errors.NotFound()
    if player.user_id == user.pk:
        return player
    if Player.objects.filter(round=found, user=user).exclude(side=side).exists():
        raise errors.Conflict(code="already_playing")
    if not Player.objects.filter(pk=player.pk, user=None, client=HUMAN).update(user=user):
        raise errors.Conflict(code="player_taken")
    log.append(found.pk, "player.joined", {"side": side, "client": HUMAN})
    player.refresh_from_db()
    return player


def reach(found: Round):
    one = slot_range(found.allocation.slot)
    return lambda role: one.runner(role)


def prepare_kibana(found: Round) -> None:
    try:
        kibana_gate.prepare_kibana(found)
    except (errors.DomainError, OSError) as failed:
        logger.warning("round %s: the Kibana space was not prepared: %s", found.pk, failed)


def start_round(found: Round) -> Round:
    if found.phase == ENDED:
        raise errors.Conflict(code="round_closed")
    if found.phase != CREATED:
        raise errors.Conflict(code="round_started")
    if found.allocation.closed is not None:
        raise errors.Conflict(code="allocation_closed")
    if Player.objects.filter(round=found, client=HUMAN, user=None).exists():
        raise errors.Conflict(code="players_open")
    if found.kind == ROUND:
        refuse_fallen(found.allocation)
    if not sandbox.slot_ready(found.allocation.slot):
        raise sandbox.unavailable()
    if not Round.objects.filter(pk=found.pk, phase=CREATED).update(phase=STARTING):
        raise errors.Conflict(code="round_started")
    try:
        frozen = content.snapshot(found.problem)
        begun = timezone.now()
        limit = (frozen.get("round") or {}).get("time_limit_s")
        found.snapshot, found.phase, found.started = frozen, STARTING, begun
        found.ends_at = begun + timedelta(seconds=int(limit)) if limit else None
        found.save(update_fields=["snapshot", "started", "ends_at"])
        defence.apply_posture(found)
        passwords = customers.fresh_passwords(found)
        baselines.take_baseline(found, reach(found), passwords)
        origins.fill_pool(found)
    except Exception:
        Round.objects.filter(pk=found.pk, phase=STARTING).update(phase=CREATED, started=None, ends_at=None)
        found.refresh_from_db()
        raise
    prepare_kibana(found)
    customers.begin(found, passwords)
    if not Round.objects.filter(pk=found.pk, phase=STARTING).update(phase=RUNNING):
        found.refresh_from_db()
        customers.stop(found)
        return found
    found.phase = RUNNING
    log.append(found.pk, "round.started", {"ends_at": found.ends_at.isoformat() if found.ends_at else None})
    return found


def guarded(found: Round, what: str, work) -> None:
    try:
        work(found)
    except (errors.DomainError, OSError) as failed:
        logger.warning("round %s: %s failed: %s", found.pk, what, failed)


def stepped(found: Round, what: str, work) -> Exception | None:
    try:
        work(found)
    except Exception as failed:
        logger.exception("round %s: %s failed", found.pk, what)
        return failed
    return None


def settle(found: Round) -> None:
    referee.settle(found, actions(found), alert_feed.detections(found))


def judge_after() -> timedelta:
    return timedelta(seconds=settings.JUDGE_AFTER_SECONDS)


def judge(found: Round, at: datetime | None = None) -> int:
    made = referee.judge(found, actions(found), alert_feed.detections(found), attack.running(found),
                         at or timezone.now(), judge_after())
    for verdict in made:
        log.append(found.pk, "case.judged", {"action": verdict.action, "case": verdict.case,
                                             "verdict": verdict.verdict, "alerts": verdict.alerts,
                                             "corroborated": verdict.corroborated})
    return len(made)


def end_time(found: Round) -> datetime:
    now = timezone.now()
    return min(now, found.ends_at) if found.ends_at else now


def end_round(found: Round, reason: str) -> Round:
    if reason not in round_rules.END_REASONS:
        raise ValueError(f"no end reason {reason!r}")
    if found.phase == RUNNING:
        final_reads(found)
    return finish(found, reason)


def finish(found: Round, reason: str) -> Round:
    was = found.phase
    if not Round.objects.filter(pk=found.pk).exclude(phase=ENDED).update(phase=ENDED, ended=end_time(found),
                                                                          end_reason=reason):
        found.refresh_from_db()
        return found
    found.refresh_from_db()
    guarded(found, "closing the attack side", attack.close)
    guarded(found, "closing the defence side", defence.close)
    if was != CREATED:
        customers.stop(found)
        wait_for_late_alerts(found)
        stepped(found, ALERTS_READ, lambda one: alert_feed.ingest_alerts(one))
        guarded(found, "settling the objectives", settle)
        stepped(found, "judging the cases", judge)
    log.append(found.pk, "round.ended", {"reason": reason})
    return found


def wait_for_late_alerts(found: Round) -> None:
    left = (found.ended + judge_after() - timezone.now()).total_seconds()
    if left > 0:
        time.sleep(left)


def forfeit(found: Round, player: Player) -> Round:
    auth.refuse_write(found)
    return end_round(found, f"forfeit_{player.side}")


def observe(found: Round) -> None:
    losses.observe_effects(found, reach(found), attack.actions(found))


ALERTS_READ = "ingesting alerts"
READS = (
    (ALERTS_READ, lambda found: alert_feed.ingest_alerts(found)),
    ("spending origins from the WAF error log", lambda found: attack.spend_from_log(found)),
    ("observing effects", observe),
    ("reading commands", lambda found: attack.read_commands(found)),
    ("ending the tool runs that finished", lambda found: attack.finished_runs(found)),
    ("recording a reload done in a defence terminal", lambda found: defence.record_terminal_reload(found)),
    ("the customers", lambda found: customers.catch_up(found)),
    ("settling the objectives", settle),
    ("judging the cases", judge),
)
FINAL_READS = tuple(read for read in READS if read[0] != "the customers")


def state_of(found: Round, at: datetime) -> RoundState:
    shown = losses.objectives(found)
    left = origins.remaining(found)
    return RoundState(
        phase=Phase(found.phase), now=at, started_at=found.started,
        time_limit_s=(found.snapshot.get("round") or {}).get("time_limit_s"),
        objectives_total=len(shown), objectives_lost=sum(1 for one in shown if one.state == losses.LOST),
        origins_total=left.total, origins_left=left.left,
        benign_passes=customers.passes(found))


def read_every() -> timedelta:
    return timedelta(seconds=settings.READ_EVERY_SECONDS)


def not_being_read(at: datetime) -> Q:
    return Q(reading_since=None) | Q(reading_since__lt=at - READ_ABANDONED)


def claim_reading(found: Round, at: datetime) -> bool:
    free = not_being_read(at)
    due = Q(read_at__lte=at - read_every()) | Q(read_at=None, started__lte=at - read_every()) | Q(ends_at__lte=at)
    return bool(Round.objects.filter(free, due, pk=found.pk, phase=RUNNING).update(reading_since=at))


def still_running(found: Round) -> bool:
    return Round.objects.filter(pk=found.pk, phase=RUNNING).exists()


def read_logs(found: Round, reads=READS) -> None:
    unavailable = {}
    for what, step in reads:
        if not still_running(found):
            found.refresh_from_db()
            return
        failed = stepped(found, what, step)
        if isinstance(failed, errors.Unavailable):
            unavailable[what] = failed.code
    found.unavailable_reads = unavailable
    Round.objects.filter(pk=found.pk).update(unavailable_reads=unavailable)


def refuse_if_unread(found: Round, what: str) -> None:
    code = found.unavailable_reads.get(what)
    if code and found.phase == RUNNING:
        raise errors.Unavailable(code=code)


def release_reading(found: Round, claimed_at: datetime) -> None:
    Round.objects.filter(pk=found.pk, reading_since=claimed_at).update(reading_since=None, read_at=timezone.now())


def wait_for_reader() -> None:
    time.sleep(READER_POLL_SECONDS)


def final_reads(found: Round) -> None:
    while True:
        at = timezone.now()
        if Round.objects.filter(not_being_read(at), pk=found.pk, phase=RUNNING).update(reading_since=at):
            break
        if not still_running(found):
            return
        wait_for_reader()
    try:
        read_logs(found, FINAL_READS)
    finally:
        release_reading(found, at)


def catch_up(found: Round, at: datetime | None = None) -> str | None:
    claimed_at = timezone.now()
    if found.phase != RUNNING or not claim_reading(found, claimed_at):
        return None
    try:
        read_logs(found)
        found.refresh_from_db()
        if found.phase != RUNNING:
            return None
        reason = round_rules.ended(state_of(found, at or timezone.now()))
        if reason is not None:
            finish(found, reason)
        return reason
    finally:
        release_reading(found, claimed_at)


def actions(found: Round):
    return attack.actions(found) + customers.benign_records(found)


def score(found: Round, correlation: str | None = None) -> referee.RoundScore:
    return referee.score(found, actions(found), alert_feed.detections(found), correlation)


def score_for(found: Round, viewer_staff: bool, operator: bool, correlation: str | None) -> referee.RoundScore:
    if correlation and not viewer_staff:
        raise errors.NotAPlayer(code="not_staff", path="correlation")
    if not operator and found.phase != ENDED:
        raise errors.Conflict(code="round_running")
    return score(found, correlation)


def terminal_open(found: Round) -> None:
    auth.refuse_write(found)


@dataclass(frozen=True)
class Shell:
    address: str
    alias: str
    account: str


TERMINALS = {"attack": ("attack", attack.terminal_shell), "defence": ("defence", defence_terminal.terminal_shell),
             "ids": ("defence", defence_terminal.ids_terminal_shell)}


def terminal_shell(round_id: int, terminal: str) -> Shell:
    found = Round.objects.select_related("allocation").filter(pk=round_id).first()
    if found is None:
        raise errors.NotFound()
    auth.refuse_write(found)
    if terminal not in TERMINALS:
        raise errors.NotAPlayer()
    side, shell_of = TERMINALS[terminal]
    player = Player.objects.filter(round=found, side=side).first()
    if player is None:
        raise errors.NotAPlayer()
    address, account = shell_of(player)
    reached = slot_range(found.allocation.slot)
    alias = reached.host_key_alias(address) if hasattr(reached, "host_key_alias") else ""
    return Shell(address=address, alias=alias or address, account=account)


def map_of(found: Round, side: str) -> dict:
    cfg = configured().range
    declared = read_declaration(Path(cfg.declaration), Path(cfg.source))
    wargame = found.allocation.wargame_id
    learner = topology.learner(declared, wargame)
    return topology.for_side(topology.graph(learner, slot_range(found.allocation.slot).wiring()), side)


def shown_side(playing: list[Player], operator: bool) -> str:
    if operator or any(player.side == "defence" for player in playing):
        return "defence"
    return "attack"


def browse(found: Round, playing: list[Player], method: str, host: str, path: str, headers: dict,
           body: str | None) -> site.Fetched:
    if not playing:
        raise errors.NotAPlayer()
    return site.browse(found, playing, method, host, path, headers, body)


def site_requests(found: Round, playing: list[Player], after: int = 0) -> list[dict]:
    if not playing:
        raise errors.NotAPlayer()
    return site.requests_of(found, playing, after)


def record_probes(wargame_id: str, user) -> Allocation:
    return probes.record(wargame_id, user)


def probe_progress(allocation_id: int) -> probes.Progress:
    return probes.progress(allocation_id)
