from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cr import errors
from cr.config import configured
from domain import round_rules
from domain.round_rules import BOT, HUMAN, LeaseState, Matchup, Phase, RoundState
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
from training.content import probes
from training.content import problems as content
from training.defence import kibana_gate
from training.defence import rules as defence
from training.defence import terminal as defence_terminal
from training.models import Lease, Round, Seat
from training.round import access as auth
from training.round import site
from training.traffic import customers
from users import seats as seat_tokens

ROUND = "round"
SIDES = ("attack", "defence")
ENDED = Phase.ENDED.value
RUNNING = Phase.RUNNING.value
CREATED = Phase.CREATED.value
STARTING = Phase.STARTING.value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Created:
    round: Round
    bot_tokens: dict[str, str]


def refuse_fallen(held: Lease) -> None:
    if not round_rules.may_start_scored(LeaseState(objective_fallen=losses.fallen_on(held.pk))):
        raise errors.Conflict(code="objective_fallen")


def seated_user(given: Any, path: str):
    found = get_user_model().objects.filter(username=given, is_active=True).first() if isinstance(given, str) else None
    if found is None:
        raise errors.Invalid(code="unknown_account", path=f"{path}.username")
    return found


def seat_of(found: Round, side: str, client: str, asked: dict) -> Seat:
    path = f"seats.{side}"
    if client == BOT:
        name = (asked.get("bot") or {}).get("name") if isinstance(asked.get("bot"), dict) else None
        if not isinstance(name, str) or not name.strip():
            raise errors.Invalid(code="invalid_choice", path=path)
        return Seat.objects.create(round=found, side=side, client=BOT, bot_name=name.strip())
    if "username" in asked:
        return Seat.objects.create(round=found, side=side, client=HUMAN, user=seated_user(asked["username"], path))
    if asked.get("open") is True:
        return Seat.objects.create(round=found, side=side, client=HUMAN)
    raise errors.Invalid(code="invalid_choice", path=path)


def create_round(held: Lease, problem_id: int, matchup: str, seats: dict[str, dict]) -> Created:
    if held.closed is not None:
        raise errors.Conflict(code="lease_closed")
    problem = content.problem(problem_id)
    if problem.wargame_id != held.wargame_id or problem.kind != ROUND:
        raise errors.Invalid(code="invalid_choice", path="problem")
    allowed = (content.snapshot(problem).get("round") or {}).get("matchups") or []
    if matchup not in allowed:
        raise errors.Invalid(code="matchup_not_allowed", path="matchup")
    if Round.objects.filter(lease=held).exclude(phase=ENDED).exists():
        raise errors.Conflict(code="round_open")
    refuse_fallen(held)
    users = [asked.get("username") for asked in seats.values() if isinstance(asked, dict) and asked.get("username")]
    if len(users) != len(set(users)):
        raise errors.Conflict(code="already_seated")
    tokens: dict[str, str] = {}
    with transaction.atomic():
        found = Round.objects.create(lease=held, problem=problem, kind=ROUND, matchup=matchup)
        made = [seat_of(found, side.value, client, dict(seats.get(side.value) or {}))
                for side, client in round_rules.SEATS[Matchup(matchup)].items()]
        for seat in made:
            if seat.client == BOT:
                tokens[seat.side] = seat_tokens.issue_token(seat)
    for seat in made:
        if seat.client == BOT or seat.user_id is not None:
            log.append(found.pk, "seat.joined", {"side": seat.side, "client": seat.client})
    return Created(round=found, bot_tokens=tokens)


def round_of(round_id: int) -> Round:
    found = Round.objects.select_related("lease").filter(pk=round_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_round")
    return found


def seats(found: Round) -> list[Seat]:
    return list(Seat.objects.filter(round=found).order_by("side"))


def rounds_for(user, mine: bool = False, state: str = "") -> list[Round]:
    found = Round.objects.select_related("lease").order_by("-id")
    if mine or (state != "joinable" and not user.is_staff):
        found = found.filter(Q(seats__user=user) | Q(lease__opened_by=user)).distinct()
    if state == "open":
        found = found.exclude(phase=ENDED)
    elif state == "joinable":
        found = found.filter(phase=CREATED, kind=ROUND, seats__client=HUMAN, seats__user=None).distinct()
    return list(found[:100])


def join(found: Round, side: str, user) -> Seat:
    if found.phase == ENDED:
        raise errors.Conflict(code="round_closed")
    seat = Seat.objects.filter(round=found, side=side).first()
    if seat is None:
        raise errors.NotFound()
    if seat.user_id == user.pk:
        return seat
    if Seat.objects.filter(round=found, user=user).exclude(side=side).exists():
        raise errors.Conflict(code="already_seated")
    if not Seat.objects.filter(pk=seat.pk, user=None, client=HUMAN).update(user=user):
        raise errors.Conflict(code="seat_taken")
    log.append(found.pk, "seat.joined", {"side": side, "client": HUMAN})
    seat.refresh_from_db()
    return seat


def reach(found: Round):
    one = slot_range(found.lease.slot)
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
    if found.lease.closed is not None:
        raise errors.Conflict(code="lease_closed")
    if Seat.objects.filter(round=found, client=HUMAN, user=None).exists():
        raise errors.Conflict(code="seats_open")
    if found.kind == ROUND:
        refuse_fallen(found.lease)
    if not sandbox.slot_ready(found.lease.slot):
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
        baselines.take_baseline(found, reach(found))
        attack.fill_pool(found)
    except Exception:
        Round.objects.filter(pk=found.pk, phase=STARTING).update(phase=CREATED, started=None, ends_at=None)
        found.refresh_from_db()
        raise
    prepare_kibana(found)
    customers.begin(found)
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


def stepped(found: Round, what: str, work) -> None:
    try:
        work(found)
    except Exception:
        logger.exception("round %s: %s failed", found.pk, what)


def settle(found: Round) -> None:
    referee.settle(found, actions(found), alert_feed.detections(found))


def end_round(found: Round, reason: str) -> Round:
    if reason not in round_rules.END_REASONS:
        raise ValueError(f"no end reason {reason!r}")
    was = found.phase
    if not Round.objects.filter(pk=found.pk).exclude(phase=ENDED).update(phase=ENDED, ended=timezone.now(),
                                                                          end_reason=reason):
        found.refresh_from_db()
        return found
    found.refresh_from_db()
    guarded(found, "closing the attack side", attack.close)
    guarded(found, "closing the defence side", defence.close)
    if was != CREATED:
        customers.stop(found)
        guarded(found, "settling the objectives", settle)
    log.append(found.pk, "round.ended", {"reason": reason})
    return found


def forfeit(found: Round, seat: Seat) -> Round:
    auth.refuse_write(found)
    return end_round(found, f"forfeit_{seat.side}")


def observe(found: Round) -> None:
    losses.observe_effects(found, reach(found), attack.actions(found))


TICK_STEPS = (
    ("ingesting alerts", lambda found: alert_feed.ingest_alerts(found)),
    ("charging from the access log", lambda found: attack.charge_from_access(found)),
    ("refilling the edge", lambda found: attack.refill_edge(found)),
    ("observing effects", observe),
    ("reading commands", lambda found: attack.read_commands(found)),
    ("checking drift", lambda found: defence.check_drift(found)),
    ("enabling expired rules", lambda found: defence.enable_expired(found)),
    ("the customers", lambda found: customers.tick(found)),
    ("settling the objectives", settle),
)


def state_of(found: Round, at: datetime) -> RoundState:
    shown = losses.objectives(found)
    hp = attack.hp(found)
    return RoundState(
        phase=Phase(found.phase), now=at, started_at=found.started,
        time_limit_s=(found.snapshot.get("round") or {}).get("time_limit_s"),
        objectives_total=len(shown), objectives_lost=sum(1 for one in shown if one.state == losses.LOST),
        origins_total=hp.origins_left + len(hp.spent), origins_left=hp.origins_left,
        benign_passes=customers.passes(found))


def tick(found: Round, at: datetime | None = None) -> str | None:
    if found.phase != RUNNING:
        return None
    for what, step in TICK_STEPS:
        stepped(found, what, step)
    found.refresh_from_db()
    reason = round_rules.ended(state_of(found, at or timezone.now()))
    if reason is not None:
        end_round(found, reason)
    return reason


def actions(found: Round):
    return attack.actions(found) + customers.benign_records(found)


def score(found: Round, correlation: str | None = None) -> referee.RoundScore:
    return referee.score(found, actions(found), alert_feed.detections(found), correlation,
                         defence.posture_drift(found))


def score_for(found: Round, viewer_staff: bool, operator: bool, correlation: str | None) -> referee.RoundScore:
    if correlation and not viewer_staff:
        raise errors.NotSeated(code="not_staff", path="correlation")
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


SHELL_OF_SIDE = {"attack": attack.terminal_shell, "defence": defence_terminal.terminal_shell}


def terminal_shell(round_id: int, side: str) -> Shell:
    found = Round.objects.select_related("lease").filter(pk=round_id).first()
    if found is None:
        raise errors.NotFound()
    auth.refuse_write(found)
    seat = Seat.objects.filter(round=found, side=side).first()
    if seat is None or side not in SHELL_OF_SIDE:
        raise errors.NotSeated()
    address, account = SHELL_OF_SIDE[side](seat)
    reached = slot_range(found.lease.slot)
    alias = reached.host_key_alias(address) if hasattr(reached, "host_key_alias") else ""
    return Shell(address=address, alias=alias or address, account=account)


def customers_prefer(wargame: str, declared) -> tuple[str, ...]:
    traffic = customers.declared_traffic(wargame)
    weights = traffic["origins"] if traffic else {}
    subnets = {origin.id: origin.subnet for origin in declared.origins if origin.id != declared.default_origin}
    return tuple(subnets[origin] for origin in sorted(weights, key=lambda one: (-weights[one], one))
                 if origin in subnets and weights[origin] > 0)


def map_of(found: Round, side: str) -> dict:
    cfg = configured().range
    declared = read_declaration(Path(cfg.declaration), Path(cfg.source))
    wargame = found.lease.wargame_id
    learner = topology.learner(declared, wargame, declared.roles.get("attacker", ""),
                               customers_prefer(wargame, declared))
    return topology.for_side(topology.graph(learner, slot_range(found.lease.slot).wiring()), side)


def shown_side(seated: list[Seat], operator: bool) -> str:
    if operator or any(seat.side == "defence" for seat in seated):
        return "defence"
    return "attack"


def running_rounds() -> list[Round]:
    return list(Round.objects.select_related("lease").filter(phase=RUNNING))


def browse(found: Round, seated: list[Seat], method: str, host: str, path: str, headers: dict,
           body: str | None) -> site.Fetched:
    if not seated:
        raise errors.NotSeated()
    return site.browse(found, seated, method, host, path, headers, body)


def site_requests(found: Round, seated: list[Seat], after: int = 0) -> list[dict]:
    if not seated:
        raise errors.NotSeated()
    return site.requests_of(found, seated, after)


def record_probes(wargame_id: str, user) -> Lease:
    return probes.record(wargame_id, user)


def probe_progress(lease_id: int) -> probes.Progress:
    return probes.progress(lease_id)
