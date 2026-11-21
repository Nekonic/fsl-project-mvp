from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from cr import errors
from domain.round_rules import Phase
from sandbox import reach
from sandbox import service as sandbox
from training.content import problems as content
from training.models import Allocation, Round
from training.round import lifecycle, retention

ROUND = "round"
ENDED = Phase.ENDED.value

choosing = threading.Lock()
kept_open: set[int] = set()


def idle() -> timedelta:
    return timedelta(minutes=settings.ALLOCATION_IDLE_MINUTES)


def held_slots() -> set[int]:
    return set(Allocation.objects.filter(closed=None).exclude(slot=None).values_list("slot", flat=True))


def open_allocation(user, wargame_id: str, purpose: str = ROUND) -> Allocation:
    if wargame_id not in {wargame.pk for wargame in content.wargames()}:
        raise errors.Invalid(code="unknown_wargame", path="wargame")
    expire()
    retention.prune()
    whole = reach.whole_range()
    with choosing:
        number = sandbox.free_slot(whole, wargame_id, held_slots())
        if number is None:
            raise sandbox.unavailable()
        return Allocation.objects.create(wargame_id=wargame_id, purpose=purpose, slot=number,
                                    opened_by=user if getattr(user, "pk", None) else None,
                                    expires_at=timezone.now() + idle(), browse_marker=uuid.uuid4().hex)


def allocation(allocation_id: int) -> Allocation:
    found = Allocation.objects.filter(pk=allocation_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_allocation")
    return found


def ready(held: Allocation) -> bool:
    return held.closed is None and sandbox.slot_ready(held.slot)


def heartbeat(held: Allocation) -> Allocation:
    if held.closed is not None:
        raise errors.Conflict(code="allocation_closed")
    held.expires_at = max(held.expires_at, timezone.now() + idle())
    held.save(update_fields=["expires_at"])
    return held


@contextmanager
def keeping_open(held: Allocation):
    kept_open.add(held.pk)
    try:
        yield
    finally:
        kept_open.discard(held.pk)


def close_allocation(held: Allocation, reason: str = "ended_by_operator") -> Allocation:
    for found in Round.objects.filter(allocation=held).exclude(phase=ENDED):
        lifecycle.end_round(found, reason)
    closed = Allocation.objects.filter(pk=held.pk, closed=None).update(closed=timezone.now())
    held.refresh_from_db()
    if closed:
        sandbox.refill_slot(held.slot, held.wargame_id)
    return held


def expire(at: datetime | None = None) -> list[int]:
    due = list(Allocation.objects.filter(closed=None, expires_at__lt=at or timezone.now()).exclude(pk__in=kept_open))
    for held in due:
        close_allocation(held, "allocation_expired")
    return [held.pk for held in due]


def close_if_expired(held: Allocation) -> bool:
    if held.closed is not None or held.expires_at >= timezone.now() or held.pk in kept_open:
        return False
    close_allocation(held, "allocation_expired")
    return True


def holders() -> dict[int, int]:
    return dict(Allocation.objects.filter(closed=None).exclude(slot=None).values_list("slot", "pk"))


def slots() -> list[sandbox.SlotLine]:
    return sandbox.slots(holders())


def fill_pool() -> list[sandbox.SlotLine]:
    sandbox.fill_pool(held_slots())
    return slots()
