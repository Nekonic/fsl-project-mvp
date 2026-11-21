from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from sandbox.runner import Drifted, RangeUnavailable

IDLE = "idle"
BUILDING = "building"
CONFIGURING = "configuring"
FAILED = "failed"
RUNNING = (BUILDING, CONFIGURING)
WAIT = 1800.0

Clock = Callable[[], float]


@dataclass(frozen=True)
class Refill:
    slot: int
    state: str = IDLE
    wargame: str = ""
    replaced: tuple[str, ...] = ()
    deadline: float = 0.0
    reason: str = ""

    @property
    def running(self) -> bool:
        return self.state in RUNNING

    def shown(self) -> dict:
        return {"state": "running" if self.running else self.state, "reason": self.reason}


class Store(Protocol):
    def get(self, slot: int) -> Refill | None:
        ...

    def put(self, refill: Refill) -> None:
        ...

    def slots(self) -> list[int]:
        ...


class MemoryStore:
    def __init__(self):
        self._held: dict[int, Refill] = {}
        self._guard = threading.Lock()

    def get(self, slot: int) -> Refill | None:
        with self._guard:
            return self._held.get(slot)

    def put(self, refill: Refill) -> None:
        with self._guard:
            self._held[refill.slot] = refill

    def slots(self) -> list[int]:
        with self._guard:
            return sorted(self._held)


class FileStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _path(self, slot: int) -> Path:
        return self.directory / f"slot-{int(slot)}.json"

    def get(self, slot: int) -> Refill | None:
        try:
            held = json.loads(self._path(slot).read_text())
        except (OSError, ValueError):
            return None
        return Refill(**{**held, "replaced": tuple(held.get("replaced") or ())})

    def put(self, refill: Refill) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(refill.slot)
        fresh = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}")
        fresh.write_text(json.dumps(asdict(refill)))
        fresh.replace(target)

    def slots(self) -> list[int]:
        if not self.directory.is_dir():
            return []
        return sorted(int(path.stem.removeprefix("slot-")) for path in self.directory.glob("slot-*.json"))


_claiming = threading.Lock()


def standing(store: Store, slot: int) -> Refill:
    return store.get(slot) or Refill(slot=slot)


def owed(store: Store) -> list[Refill]:
    return [refill for slot in store.slots() if (refill := standing(store, slot)).running]


def claim(store: Store, clock: Clock, slot: int, wargame: str = "", replaced: tuple[str, ...] = (),
          wait: float = WAIT) -> bool:
    with _claiming:
        if standing(store, slot).running:
            return False
        store.put(Refill(slot=slot, state=BUILDING, wargame=wargame, replaced=tuple(replaced),
                         deadline=clock() + wait))
        return True


def release(store: Store, slot: int) -> None:
    store.put(Refill(slot=slot))


def failed(store: Store, slot: int, reason: str) -> None:
    store.put(replace(standing(store, slot), state=FAILED, reason=reason))


def configured_by_hand(store: Store, slot: int) -> None:
    if standing(store, slot).state == FAILED:
        release(store, slot)


def advance(store: Store, clock: Clock, adapter) -> Refill:
    refill = standing(store, adapter.slot)
    if not refill.running:
        return refill
    try:
        refill = _stepped(refill, clock, adapter)
    except Exception as exc:
        refill = replace(refill, state=FAILED, reason=str(exc) or type(exc).__name__)
    store.put(refill)
    return refill


def _stepped(refill: Refill, clock: Clock, adapter) -> Refill:
    if refill.state == BUILDING:
        if not _built(refill, adapter):
            return _waiting(refill, clock, f"slot {refill.slot}'s stack was not created and set up in time")
        refill = replace(refill, state=CONFIGURING)
    try:
        adapter.configure_slot()
    except RangeUnavailable as exc:
        return _waiting(refill, clock, f"the baseline rules did not reach slot {refill.slot} in time: {exc}")
    return Refill(slot=refill.slot)


def _built(refill: Refill, adapter) -> bool:
    try:
        plan = adapter.ensure_slot(wargame=refill.wargame)
    except RangeUnavailable:
        return False
    if plan.failures:
        raise Drifted("; ".join(plan.failures))
    return plan.active and plan.stack_id not in refill.replaced


def _waiting(refill: Refill, clock: Clock, gave_up: str) -> Refill:
    if clock() >= refill.deadline:
        return replace(refill, state=FAILED, reason=gave_up)
    return refill
