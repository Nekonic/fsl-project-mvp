from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from attack import service as attack
from content import service as content
from cr import config, errors
from defence import service as defence
from domain import round_rules
from domain.round_rules import BOT, HUMAN, LeaseState, Matchup, Phase, RoundState
from events import log
from match import auth, customers, probes, site
from match.models import Lease, Round, Seat
from range import refill, substrate, topology
from range.declaration import read as read_declaration
from referee import service as referee

RETRY_AFTER = 30
ROUND, LESSON = "round", "lesson"
SIDES = ("attack", "defence")
ENDED = Phase.ENDED.value
RUNNING = Phase.RUNNING.value
CREATED = Phase.CREATED.value
STARTING = Phase.STARTING.value

logger = logging.getLogger(__name__)
choosing = threading.Lock()


@dataclass(frozen=True)
class Created:
    round: Round
    bot_tokens: dict[str, str]


@dataclass(frozen=True)
class SlotLine:
    slot: int
    wargame: str
    lease: int | None
    refill: dict


@dataclass(frozen=True)
class Removed:
    kind: str
    id: str


@dataclass(frozen=True)
class Fabric:
    present: tuple[str, ...]
    clean: bool


@dataclass(frozen=True)
class Server:
    host: str
    server: str
    status: str


@dataclass(frozen=True)
class SlotStanding:
    slot: int
    wargame: str
    servers: tuple[Server, ...]
    blocked: tuple[str, ...]
    failures: tuple[str, ...]


def configured() -> config.Config:
    return config.build(source=Path(settings.CR_SOURCE))


def whole_range():
    return substrate.substrate(configured().range)


def slot_range(number: int | None):
    whole = whole_range()
    return whole.in_slot(number) if hasattr(whole, "in_slot") and number else whole


def store() -> refill.Store:
    return refill.FileStore(configured().refill.directory)


def clock() -> float:
    return time.time()


def now() -> datetime:
    return timezone.now()


def idle() -> timedelta:
    return timedelta(minutes=settings.LEASE_IDLE_MINUTES)


def numbers(whole) -> list[int]:
    return list(range(1, whole.slots + 1)) if hasattr(whole, "in_slot") else [1]


def assigned(whole, number: int) -> str:
    return whole.in_slot(number).wargame if hasattr(whole, "in_slot") else ""


def held_slots() -> set[int]:
    return set(Lease.objects.filter(closed=None).exclude(slot=None).values_list("slot", flat=True))


def slot_ready(number: int | None) -> bool:
    return number is not None and refill.standing(store(), number).state == refill.IDLE


def free_slot(whole, wargame: str) -> int | None:
    held = held_slots()
    return next((number for number in numbers(whole)
                 if number not in held and assigned(whole, number) in ("", wargame) and slot_ready(number)), None)


def unavailable() -> errors.Unavailable:
    return errors.Unavailable(code="range_unavailable", params={"retry_after": RETRY_AFTER})


def open_lease(user, wargame_id: str, purpose: str = ROUND) -> Lease:
    if wargame_id not in {wargame.pk for wargame in content.wargames()}:
        raise errors.Invalid(code="unknown_wargame", path="wargame")
    whole = whole_range()
    with choosing:
        number = free_slot(whole, wargame_id)
        if number is None:
            raise unavailable()
        return Lease.objects.create(wargame_id=wargame_id, purpose=purpose, slot=number,
                                    opened_by=user if getattr(user, "pk", None) else None,
                                    expires_at=now() + idle(), browse_marker=uuid.uuid4().hex)


def lease(lease_id: int) -> Lease:
    found = Lease.objects.filter(pk=lease_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_lease")
    return found


def ready(held: Lease) -> bool:
    return held.closed is None and slot_ready(held.slot)


def heartbeat(held: Lease) -> Lease:
    if held.closed is not None:
        raise errors.Conflict(code="lease_closed")
    held.expires_at = max(held.expires_at, now() + idle())
    held.save(update_fields=["expires_at"])
    return held


def refill_slot(held: Lease) -> None:
    if not held.slot:
        return
    kept = store()
    try:
        replaced = tuple(ident for _, ident in slot_range(held.slot).reset_slot())
    except errors.DomainError as failed:
        refill.failed(kept, held.slot, str(failed) or type(failed).__name__)
        return
    refill.claim(kept, clock, held.slot, held.wargame_id, replaced, wait=configured().refill.wait)


def close_lease(held: Lease, reason: str = "ended_by_operator") -> Lease:
    for found in Round.objects.filter(lease=held).exclude(phase=ENDED):
        end_round(found, reason)
    closed = Lease.objects.filter(pk=held.pk, closed=None).update(closed=now())
    held.refresh_from_db()
    if closed:
        refill_slot(held)
    return held


def refuse_fallen(held: Lease) -> None:
    if not round_rules.may_start_scored(LeaseState(objective_fallen=referee.fallen_on(held.pk))):
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
                tokens[seat.side] = auth.issue_token(seat)
    for seat in made:
        if seat.client == BOT or seat.user_id is not None:
            log.append(found.pk, "seat.joined", {"side": seat.side, "client": seat.client})
    return Created(round=found, bot_tokens=tokens)


def lesson_sides(problem_side: str) -> tuple[str, ...]:
    return SIDES if problem_side == "both" else (problem_side,)


def create_lesson_round(held: Lease, problem_id: int, user) -> Round:
    if held.closed is not None:
        raise errors.Conflict(code="lease_closed")
    problem = content.problem(problem_id)
    if problem.wargame_id != held.wargame_id or problem.kind != LESSON:
        raise errors.Invalid(code="invalid_choice", path="problem")
    if Round.objects.filter(lease=held).exclude(phase=ENDED).exists():
        raise errors.Conflict(code="round_open")
    sides = lesson_sides(problem.side)
    with transaction.atomic():
        found = Round.objects.create(lease=held, problem=problem, kind=LESSON)
        for side in sides:
            Seat.objects.create(round=found, side=side, client=HUMAN, user=user)
    for side in sides:
        log.append(found.pk, "seat.joined", {"side": side, "client": HUMAN})
    return found


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
    if found.kind != LESSON and Seat.objects.filter(round=found, user=user).exclude(side=side).exists():
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
        defence.prepare_kibana(found)
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
    if not slot_ready(found.lease.slot):
        raise unavailable()
    if not Round.objects.filter(pk=found.pk, phase=CREATED).update(phase=STARTING):
        raise errors.Conflict(code="round_started")
    try:
        frozen = content.snapshot(found.problem)
        begun = now()
        limit = (frozen.get("round") or {}).get("time_limit_s")
        found.snapshot, found.phase, found.started = frozen, STARTING, begun
        found.ends_at = begun + timedelta(seconds=int(limit)) if limit else None
        found.save(update_fields=["snapshot", "started", "ends_at"])
        defence.apply_posture(found)
        referee.take_baseline(found, reach(found))
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
    referee.settle(found, actions(found), defence.detections(found))


def end_round(found: Round, reason: str) -> Round:
    if reason not in round_rules.END_REASONS:
        raise ValueError(f"no end reason {reason!r}")
    was = found.phase
    if not Round.objects.filter(pk=found.pk).exclude(phase=ENDED).update(phase=ENDED, ended=now(),
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
    referee.observe_effects(found, reach(found), attack.actions(found))


TICK_STEPS = (
    ("ingesting alerts", lambda found: defence.ingest_alerts(found)),
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
    shown = referee.objectives(found)
    hp = attack.hp(found)
    return RoundState(
        phase=Phase(found.phase), now=at, started_at=found.started,
        time_limit_s=(found.snapshot.get("round") or {}).get("time_limit_s"),
        objectives_total=len(shown), objectives_lost=sum(1 for one in shown if one.state == referee.LOST),
        origins_total=hp.origins_left + len(hp.spent), origins_left=hp.origins_left,
        benign_passes=customers.passes(found))


def tick(found: Round, at: datetime | None = None) -> str | None:
    if found.phase != RUNNING:
        return None
    for what, step in TICK_STEPS:
        stepped(found, what, step)
    found.refresh_from_db()
    reason = round_rules.ended(state_of(found, at or now()))
    if reason is not None:
        end_round(found, reason)
    return reason


def actions(found: Round):
    return attack.actions(found) + customers.benign_records(found)


def score(found: Round, correlation: str | None = None) -> referee.RoundScore:
    return referee.score(found, actions(found), defence.detections(found), correlation,
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


SHELL_OF_SIDE = {"attack": attack.terminal_shell, "defence": defence.terminal_shell}


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


def slots() -> list[SlotLine]:
    whole, kept = whole_range(), store()
    holders = dict(Lease.objects.filter(closed=None).exclude(slot=None).values_list("slot", "pk"))
    return [SlotLine(slot=number, wargame=assigned(whole, number), lease=holders.get(number),
                     refill=refill.standing(kept, number).shown()) for number in numbers(whole)]


def cloud_range():
    whole = whole_range()
    if not hasattr(whole, "ensure_fabric"):
        raise errors.Conflict(code="range_not_cloud")
    return whole


def removed(pairs) -> list[Removed]:
    return [Removed(kind=kind, id=str(ident)) for kind, ident in pairs]


def build_fabric() -> Fabric:
    plan = cloud_range().ensure_fabric()
    return Fabric(present=tuple(plan.present), clean=plan.clean)


def remove_fabric() -> list[Removed]:
    return removed(cloud_range().teardown_fabric())


def remove_leftovers() -> list[Removed]:
    return removed(cloud_range().clean_leftovers())


def pool_standing() -> list[SlotStanding]:
    whole = cloud_range()
    return [SlotStanding(slot=number, wargame=plan.wargame or assigned(whole, number),
                         servers=tuple(Server(host=host, server=server, status=status)
                                       for host, server, status in plan.standing),
                         blocked=tuple(plan.blocked), failures=tuple(plan.failures))
            for number, plan in zip(numbers(whole), whole.plan_slots())]


def fill_pool() -> list[SlotLine]:
    whole, kept, held = cloud_range(), store(), held_slots()
    for number in numbers(whole):
        if number not in held:
            refill.claim(kept, clock, number, assigned(whole, number), wait=configured().refill.wait)
    return slots()


def empty_pool() -> list[Removed]:
    whole, kept = cloud_range(), store()
    for number in numbers(whole):
        refill.release(kept, number)
    return [one for number in numbers(whole) for one in removed(whole.in_slot(number).teardown_slot())]


def expire(at: datetime | None = None) -> list[int]:
    due = list(Lease.objects.filter(closed=None, expires_at__lt=at or now()))
    for held in due:
        close_lease(held, "lease_expired")
    return [held.pk for held in due]


def advance_refills() -> list[refill.Refill]:
    kept, whole = store(), whole_range()
    return [refill.advance(kept, clock, whole.in_slot(owed.slot) if hasattr(whole, "in_slot") else whole)
            for owed in refill.owed(kept)]


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
