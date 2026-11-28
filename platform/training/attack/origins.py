from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from cr import errors
from cr.config import configured
from domain.round_rules import Phase
from domain.types import ENGINE_WAF, RESPONSE_ORIGIN, ResponseRecord
from sandbox import attacker as box
from sandbox import crs, customers, edge
from sandbox.substrate import range_of
from telemetry import waf_log
from telemetry import events as log
from telemetry.models import AccessCursor
from training.models import Origin, Round, RuleSet

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


def spends(found: Round) -> list[ResponseRecord]:
    return [ResponseRecord(at=row.spent_at, kind=RESPONSE_ORIGIN, source_ip=row.ip) for row in rows(found)
            if row.spent_at is not None and row.spent_by != GIVEN_UP]


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
    load_edge(found, reached)
    worn = current_of(rows(found))
    if worn is not None:
        box.wear_origin({"source_ip": worn.ip}, reached.runner(PROXY))
    return remaining(found)


def customer_origins(found: Round) -> list[dict]:
    return customers.customer_origins(range_of(found).describe(), configured().box)


def customer_addresses(found: Round) -> list[str]:
    return [address for origin in customer_origins(found) for address in origin["addresses"]]


def load_edge(found: Round, reached) -> None:
    held = rows(found)
    pool = [row.ip for row in held]
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


def waf_versions(found: Round) -> list[tuple[datetime, crs.LimitZones]]:
    return [(held.took_effect, crs.limit_zones_in("\n".join(held.files.values())))
            for held in RuleSet.objects.filter(round=found, engine=ENGINE_WAF).order_by("version")]


def zones_at(versions: Sequence[tuple[datetime, crs.LimitZones]], at: datetime) -> crs.LimitZones:
    in_force = [zones for since, zones in versions if since <= at]
    if in_force:
        return in_force[-1]
    return versions[0][1] if versions else crs.LimitZones(rates={}, shared=frozenset())


def warned_once(found: Round, held: AccessCursor, key: str, kind: str, body: dict) -> None:
    warned = held.cursor.get("limit_warned", {})
    told = set(warned.get(str(found.pk), []))
    if key in told:
        return
    log.append(found.pk, kind, body, player_side="defence")
    held.cursor = {**held.cursor, "limit_warned": {**warned, str(found.pk): sorted(told | {key})}}
    held.save(update_fields=["cursor"])


def counted(found: Round, refusal: waf_log.Refusal, held: AccessCursor,
            versions: Sequence[tuple[datetime, crs.LimitZones]]) -> bool:
    if refusal.by == waf_log.DENY:
        return True
    zones = zones_at(versions, refusal.at)
    if refusal.zone in zones.shared:
        warned_once(found, held, f"shared:{refusal.zone}", "limit.shared_key", {"zone": refusal.zone})
        return False
    floor = floor_of(found)
    if not floor:
        return True
    rate = zones.rates.get(refusal.zone)
    if rate is None:
        return False
    if rate < floor:
        warned_once(found, held, f"{refusal.zone}:{rate}", "limit.below_floor",
                    {"zone": refusal.zone, "rate_rpm": rate, "floor_rpm": floor})
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
    versions: list[tuple[datetime, crs.LimitZones]] | None = None
    fallen: list[Origin] = []
    for _ in range(ERROR_PAGES):
        found_refusals, moved = waf_log.refusals(found, cursor)
        for refusal in found_refusals:
            if refusal.ip not in open_ips or not within(found, refusal.at):
                continue
            if refusal.by == waf_log.LIMIT_REQ and versions is None:
                versions = waf_versions(found)
            if not counted(found, refusal, held, versions or []):
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
