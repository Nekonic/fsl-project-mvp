import threading

from django.conf import settings
from django.db import connection

from training.models import Allocation, Round
from training.round import allocation as allocations
from training.round import lifecycle, records

_reading: set[tuple[int | None, int | None]] = set()
_reading_lock = threading.Lock()


def catch_up(request) -> None:
    found = getattr(request, "round", None)
    held = getattr(request, "allocation", None) or (found.allocation if found is not None else None)
    if settings.READ_IN_BACKGROUND:
        read_behind(found.pk if found is not None else None, held.pk if held is not None else None)
        return
    read_now(found, held)


def read_now(found, held) -> None:
    if found is not None:
        lifecycle.catch_up(found)
    elif held is not None:
        for running in held.rounds.filter(phase=lifecycle.RUNNING):
            lifecycle.catch_up(running)
    if held is not None:
        allocations.close_if_expired(held)
    if found is not None:
        found.refresh_from_db()
        found.allocation.refresh_from_db()
        records.keep_when_due(found)


def read_behind(round_id: int | None, allocation_id: int | None) -> None:
    key = (round_id, allocation_id)
    with _reading_lock:
        if key in _reading:
            return
        _reading.add(key)
    threading.Thread(target=read_apart, args=(key,), daemon=True).start()


def read_apart(key: tuple[int | None, int | None]) -> None:
    round_id, allocation_id = key
    try:
        found = Round.objects.select_related("allocation").filter(pk=round_id).first() if round_id else None
        held = found.allocation if found is not None else (
            Allocation.objects.filter(pk=allocation_id).first() if allocation_id else None)
        read_now(found, held)
    except Exception:
        lifecycle.logger.exception("reading behind round %s, allocation %s failed", round_id, allocation_id)
    finally:
        with _reading_lock:
            _reading.discard(key)
        connection.close()
