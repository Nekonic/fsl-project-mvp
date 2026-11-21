from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sandbox import service as sandbox
from training.round import allocation as allocations
from training.round import lifecycle as service
from training.round import retention

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Followed:
    refilled: int
    expired: tuple[int, ...]
    ticked: tuple[int, ...]
    ended: tuple[tuple[int, str], ...]
    pruned: tuple[int, ...]


def guarded(what: str, work: Callable, fallback):
    try:
        return work()
    except Exception:
        logger.exception("follow: %s failed", what)
        return fallback


def once(now: datetime | None = None) -> Followed:
    refilled = guarded("driving the refills", sandbox.advance_refills, [])
    expired = guarded("closing expired allocations", lambda: allocations.expire(now), [])
    ticked, ended = [], []
    for found in guarded("listing the running rounds", service.running_rounds, []):
        reason = guarded(f"ticking round {found.pk}", lambda: service.tick(found, now), None)
        ticked.append(found.pk)
        if reason:
            ended.append((found.pk, reason))
    pruned = guarded("pruning closed allocations", lambda: retention.prune(now), [])
    return Followed(refilled=len(refilled), expired=tuple(expired), ticked=tuple(ticked), ended=tuple(ended),
                    pruned=tuple(pruned))


def run(every: float, rounds: int | None = None, pause: Callable[[float], None] = time.sleep) -> int:
    done = 0
    while rounds is None or done < rounds:
        started = time.monotonic()
        once()
        done += 1
        if rounds is None or done < rounds:
            pause(max(0.0, every - (time.monotonic() - started)))
    return done
