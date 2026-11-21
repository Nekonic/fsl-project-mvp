from __future__ import annotations

import time
from dataclasses import dataclass

from cr import errors
from cr.config import configured
from sandbox import reach, refill

RETRY_AFTER = 30


@dataclass(frozen=True)
class SlotLine:
    slot: int
    wargame: str
    allocation: int | None
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


def store() -> refill.Store:
    return refill.FileStore(configured().refill.directory)


def clock() -> float:
    return time.time()


def numbers(whole) -> list[int]:
    return list(range(1, whole.slots + 1)) if hasattr(whole, "in_slot") else [1]


def assigned(whole, number: int) -> str:
    return whole.in_slot(number).wargame if hasattr(whole, "in_slot") else ""


def slot_ready(number: int | None) -> bool:
    return number is not None and refill.standing(store(), number).state == refill.IDLE


def free_slot(whole, wargame: str, held: set[int]) -> int | None:
    return next((number for number in numbers(whole)
                 if number not in held and assigned(whole, number) in ("", wargame) and slot_ready(number)), None)


def unavailable() -> errors.Unavailable:
    return errors.Unavailable(code="range_unavailable", params={"retry_after": RETRY_AFTER})


def refill_slot(slot: int | None, wargame: str) -> None:
    if not slot:
        return
    kept = store()
    try:
        replaced = tuple(ident for _, ident in reach.slot_range(slot).reset_slot())
    except errors.DomainError as failed:
        refill.failed(kept, slot, str(failed) or type(failed).__name__)
        return
    refill.claim(kept, clock, slot, wargame, replaced, wait=configured().refill.wait)


def slots(holders: dict[int, int]) -> list[SlotLine]:
    whole, kept = reach.whole_range(), store()
    return [SlotLine(slot=number, wargame=assigned(whole, number), allocation=holders.get(number),
                     refill=refill.standing(kept, number).shown()) for number in numbers(whole)]


def cloud_range():
    whole = reach.whole_range()
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


def fill_pool(held: set[int]) -> None:
    whole, kept = cloud_range(), store()
    for number in numbers(whole):
        if number not in held:
            refill.claim(kept, clock, number, assigned(whole, number), wait=configured().refill.wait)


def empty_pool() -> list[Removed]:
    whole, kept = cloud_range(), store()
    for number in numbers(whole):
        refill.release(kept, number)
    return [one for number in numbers(whole) for one in removed(whole.in_slot(number).teardown_slot())]


def advance_refills() -> list[refill.Refill]:
    kept, whole = store(), reach.whole_range()
    return [refill.advance(kept, clock, whole.in_slot(owed.slot) if hasattr(whole, "in_slot") else whole)
            for owed in refill.owed(kept)]
