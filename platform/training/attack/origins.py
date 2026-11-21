from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from cr import errors
from cr.config import configured
from domain.round_rules import Phase
from sandbox import attacker as box
from sandbox import crs, edge
from sandbox.reach import range_of
from telemetry import access as access_log
from telemetry import events as log
from telemetry.models import AccessCursor
from training.models import Origin, Round

ATTACKER = box.ATTACKER_ROLE
PROXY = "proxy"
ERROR_PAGES = 10
GIVEN_UP = "player"


@dataclass(frozen=True)
class Current:
    id: str
    label: str
    ip: str


@dataclass(frozen=True)
class Remaining:
    origin: Current | None
    left: int
    total: int
    spent: tuple[str, ...]


@dataclass(frozen=True)
class OriginLine:
    id: str
    label: str
    ip: str
    spent_at: datetime | None
    spent_by: str


def rows(found: Round) -> list[Origin]:
    return list(Origin.objects.filter(round=found))


def current_of(held: Sequence[Origin]) -> Origin | None:
    return next((row for row in held if row.spent_at is None), None)


def remaining_of(held: Sequence[Origin]) -> Remaining:
    worn = current_of(held)
    return Remaining(origin=Current(id=worn.origin_id, label=worn.label, ip=worn.ip) if worn else None,
                     left=sum(1 for row in held if row.spent_at is None), total=len(held),
                     spent=tuple(row.ip for row in held if row.spent_at is not None))


def remaining(found: Round) -> Remaining:
    return remaining_of(rows(found))


def lines(held: Sequence[Origin]) -> tuple[OriginLine, ...]:
    return tuple(OriginLine(id=row.origin_id, label=row.label, ip=row.ip, spent_at=row.spent_at,
                            spent_by=row.spent_by) for row in held)


def attack_ips(found: Round) -> set[str]:
    return {row.ip for row in rows(found)}


def allow_writes(found: Round) -> None:
    held = rows(found)
    if held and current_of(held) is None:
        raise errors.Conflict(code="origins_spent")


def wearing(found: Round) -> Origin:
    held = rows(found)
    if not held:
        fill_pool(found)
        held = rows(found)
    worn = current_of(held)
    if worn is None:
        raise errors.Conflict(code="origins_spent")
    return worn


def fill_pool(found: Round) -> Remaining:
    settings, reached = configured(), range_of(found)
    described = reached.describe()
    offered = sorted(box.origins(described, settings.box), key=lambda origin: (not origin["default"], origin["id"]))
    if not offered:
        raise box.AttackerUnavailable("the attacker box stands on no origin")
    with transaction.atomic():
        for origin in offered:
            Origin.objects.get_or_create(round=found, ip=origin["source_ip"],
                                         defaults={"origin_id": origin["id"], "label": origin["label"]})
        AccessCursor.objects.get_or_create(allocation=found.allocation)
    load_edge(found, reached, described)
    worn = current_of(rows(found))
    if worn is not None:
        box.wear_origin({"source_ip": worn.ip}, reached.runner(PROXY))
    return remaining(found)


def customer_origins(found: Round, reached=None, described=None) -> list[dict]:
    settings = configured()
    reached = reached or range_of(found)
    described = described or reached.describe()
    unbound = box.unbound_source(reached.runner(ATTACKER), settings.box)
    return box.customer_origins(described, settings.box, unbound)


def customer_addresses(found: Round, reached=None, described=None) -> list[str]:
    return [address for origin in customer_origins(found, reached, described) for address in origin["addresses"]]


def load_edge(found: Round, reached, described) -> None:
    held = rows(found)
    pool = [row.ip for row in held] + customer_addresses(found, reached, described)
    spent = [row.ip for row in held if row.spent_at is not None]
    settings = configured()
    edge.restart(reached.runner(settings.edge.role), pool, spent, settings.edge)


def close_edge(found: Round) -> None:
    if not rows(found):
        return
    settings = configured()
    edge.restart(range_of(found).runner(settings.edge.role), (), (), settings.edge)


def marked_spent(found: Round, ip: str, at: datetime, by: str) -> Origin | None:
    with transaction.atomic():
        if not Origin.objects.select_for_update().filter(round=found, ip=ip, spent_at=None).update(
                spent_at=at, spent_by=by):
            return None
    return Origin.objects.get(round=found, ip=ip)


def give_up(found: Round, worn: Origin) -> Origin | None:
    return marked_spent(found, worn.ip, timezone.now(), GIVEN_UP)


def cut(found: Round, fallen: Sequence[Origin], reached) -> list[errors.Unavailable]:
    settings = configured()
    for row in fallen:
        log.append(found.pk, "origin.spent", {"ip": row.ip, "by": row.spent_by}, player_side="attack")
    router = reached.runner(settings.edge.role)
    refused: list[errors.Unavailable] = []
    for row in fallen:
        try:
            edge.spend(router, row.ip, settings.edge)
        except errors.Unavailable as failed:
            refused.append(failed)
    following = current_of(rows(found))
    if following is None:
        log.append(found.pk, "origins.spent", {}, player_side="attack")
    else:
        box.wear_origin({"source_ip": following.ip}, reached.runner(PROXY))
        log.append(found.pk, "origin.switched", {"ip": following.ip}, player_side="attack")
    return refused


def floor_of(found: Round) -> int | None:
    return (found.snapshot.get("round") or {}).get("limit_floor_rpm")


def zone_rates(found: Round) -> dict[str, int]:
    settings = configured()
    return crs.limit_rates(range_of(found).runner(settings.waf.role))


def warn_below_floor(found: Round, held: AccessCursor, zone: str, rate: int, floor: int) -> None:
    warned = held.cursor.get("limit_warned", {})
    told = set(warned.get(str(found.pk), []))
    if f"{zone}:{rate}" in told:
        return
    log.append(found.pk, "limit.below_floor", {"zone": zone, "rate_rpm": rate, "floor_rpm": floor},
               player_side="defence")
    held.cursor = {**held.cursor, "limit_warned": {**warned, str(found.pk): sorted(told | {f"{zone}:{rate}"})}}
    held.save(update_fields=["cursor"])


def counted(found: Round, refusal: access_log.Refusal, held: AccessCursor, rates: dict[str, int] | None) -> bool:
    if refusal.by == access_log.DENY:
        return True
    floor = floor_of(found)
    if not floor:
        return True
    rate = (rates or {}).get(refusal.zone)
    if rate is None:
        return False
    if rate < floor:
        warn_below_floor(found, held, refusal.zone, rate, floor)
        return False
    return True


def within(found: Round, at: datetime) -> bool:
    return (found.started is not None and at >= found.started
            and (found.ends_at is None or at <= found.ends_at))


def spent_by_log(found: Round) -> list[Origin]:
    open_ips = {row.ip for row in rows(found) if row.spent_at is None}
    if not open_ips or found.phase != Phase.RUNNING.value:
        return []
    held, _ = AccessCursor.objects.get_or_create(allocation=found.allocation)
    cursor = held.cursor.get("errors")
    rates: dict[str, int] | None = None
    fallen: list[Origin] = []
    for _ in range(ERROR_PAGES):
        found_refusals, moved = access_log.refusals(found, cursor)
        for refusal in found_refusals:
            if refusal.ip not in open_ips or not within(found, refusal.at):
                continue
            if refusal.by == access_log.LIMIT_REQ and rates is None and floor_of(found):
                rates = zone_rates(found)
            if not counted(found, refusal, held, rates):
                continue
            row = marked_spent(found, refusal.ip, refusal.at, refusal.by)
            if row is not None:
                open_ips.discard(row.ip)
                fallen.append(row)
        held.cursor = {**held.cursor, "errors": moved}
        held.save(update_fields=["cursor"])
        if moved == cursor or not open_ips:
            break
        cursor = moved
    return fallen
