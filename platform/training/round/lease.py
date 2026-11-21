from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from cr import errors
from domain.round_rules import Phase
from sandbox import reach
from sandbox import service as sandbox
from training.content import problems as content
from training.models import Lease, Round
from training.round import lifecycle

ROUND = "round"
ENDED = Phase.ENDED.value

choosing = threading.Lock()


def idle() -> timedelta:
    return timedelta(minutes=settings.LEASE_IDLE_MINUTES)


def held_slots() -> set[int]:
    return set(Lease.objects.filter(closed=None).exclude(slot=None).values_list("slot", flat=True))


def open_lease(user, wargame_id: str, purpose: str = ROUND) -> Lease:
    if wargame_id not in {wargame.pk for wargame in content.wargames()}:
        raise errors.Invalid(code="unknown_wargame", path="wargame")
    whole = reach.whole_range()
    with choosing:
        number = sandbox.free_slot(whole, wargame_id, held_slots())
        if number is None:
            raise sandbox.unavailable()
        return Lease.objects.create(wargame_id=wargame_id, purpose=purpose, slot=number,
                                    opened_by=user if getattr(user, "pk", None) else None,
                                    expires_at=timezone.now() + idle(), browse_marker=uuid.uuid4().hex)


def lease(lease_id: int) -> Lease:
    found = Lease.objects.filter(pk=lease_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_lease")
    return found


def ready(held: Lease) -> bool:
    return held.closed is None and sandbox.slot_ready(held.slot)


def heartbeat(held: Lease) -> Lease:
    if held.closed is not None:
        raise errors.Conflict(code="lease_closed")
    held.expires_at = max(held.expires_at, timezone.now() + idle())
    held.save(update_fields=["expires_at"])
    return held


def close_lease(held: Lease, reason: str = "ended_by_operator") -> Lease:
    for found in Round.objects.filter(lease=held).exclude(phase=ENDED):
        lifecycle.end_round(found, reason)
    closed = Lease.objects.filter(pk=held.pk, closed=None).update(closed=timezone.now())
    held.refresh_from_db()
    if closed:
        sandbox.refill_slot(held.slot, held.wargame_id)
    return held


def expire(at: datetime | None = None) -> list[int]:
    due = list(Lease.objects.filter(closed=None, expires_at__lt=at or timezone.now()))
    for held in due:
        close_lease(held, "lease_expired")
    return [held.pk for held in due]


def holders() -> dict[int, int]:
    return dict(Lease.objects.filter(closed=None).exclude(slot=None).values_list("slot", "pk"))


def slots() -> list[sandbox.SlotLine]:
    return sandbox.slots(holders())


def fill_pool() -> list[sandbox.SlotLine]:
    sandbox.fill_pool(held_slots())
    return slots()
