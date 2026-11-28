import pytest

from sandbox import refill
from sandbox.pool import Plan
from sandbox.runner import Drifted, RangeUnavailable


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Slot:
    def __init__(self, slot=1, plans=(), configure=()):
        self.slot = slot
        self.plans = list(plans)
        self.configure = list(configure)
        self.ensured, self.configured = [], 0

    def ensure_slot(self, wargame=""):
        self.ensured.append(wargame)
        step = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
        if isinstance(step, Exception):
            raise step
        return step

    def configure_slot(self):
        self.configured += 1
        step = self.configure.pop(0) if self.configure else None
        if isinstance(step, Exception):
            raise step
        return []


ACTIVE = Plan(standing=(("cr-slot-1-kali", "s1", "ACTIVE"),), stack_id="new")
OLD = Plan(standing=(("cr-slot-1-kali", "s0", "ACTIVE"),), stack_id="old")
BUILDING = Plan(standing=(("cr-slot-1-kali", "s1", "BUILD"),), stack_id="new")


@pytest.fixture(params=["memory", "files"])
def store(request, tmp_path):
    return refill.MemoryStore() if request.param == "memory" else refill.FileStore(tmp_path / "refill")


def test_a_claimed_slot_refills_one_advance_at_a_time_until_its_new_stack_is_set_up(store):
    clock, slot = Clock(), Slot(plans=[OLD, BUILDING, ACTIVE])

    assert refill.claim(store, clock, 1, "board", replaced=("old",))
    assert refill.advance(store, clock, slot).state == refill.BUILDING
    assert refill.advance(store, clock, slot).state == refill.BUILDING
    done = refill.advance(store, clock, slot)

    assert done.state == refill.IDLE and slot.configured == 1
    assert slot.ensured == ["board", "board", "board"]
    assert refill.owed(store) == []


def test_a_slot_already_refilling_cannot_be_claimed_twice(store):
    clock = Clock()

    assert refill.claim(store, clock, 1)
    assert not refill.claim(store, clock, 1)
    assert [one.slot for one in refill.owed(store)] == [1]


def test_an_unreachable_cloud_is_waited_for_until_the_deadline(store):
    clock, slot = Clock(), Slot(plans=[RangeUnavailable("keystone down")])
    refill.claim(store, clock, 1, wait=60)

    assert refill.advance(store, clock, slot).state == refill.BUILDING
    clock.now += 61
    gave_up = refill.advance(store, clock, slot)

    assert gave_up.state == refill.FAILED and "in time" in gave_up.reason


def test_configure_is_retried_while_the_slot_is_unreachable_then_succeeds(store):
    clock, slot = Clock(), Slot(plans=[ACTIVE], configure=[RangeUnavailable("ssh refused")])
    refill.claim(store, clock, 1)

    assert refill.advance(store, clock, slot).state == refill.CONFIGURING
    assert refill.advance(store, clock, slot).state == refill.IDLE
    assert slot.configured == 2


@pytest.mark.parametrize("plan, configure, said", [
    (Plan(standing=(("k", "s", "ACTIVE"),), failures=("cr-slot-1-target failed its setup",)), [], "failed its setup"),
    (ACTIVE, [Drifted("baseline rules did not load")], "baseline rules"),
    (ACTIVE, [KeyError("rules")], "rules"),
])
def test_a_slot_that_cannot_be_refilled_fails_with_the_reason(store, plan, configure, said):
    clock = Clock()
    refill.claim(store, clock, 1)

    failed = refill.advance(store, clock, Slot(plans=[plan], configure=configure))

    assert failed.state == refill.FAILED and said in failed.reason
    assert refill.standing(store, 1).shown() == {"state": "failed", "reason": failed.reason}


def test_a_failed_slot_configured_by_hand_is_idle_again_and_can_be_claimed(store):
    clock = Clock()
    refill.claim(store, clock, 1)
    refill.failed(store, 1, "boom")

    refill.configured_by_hand(store, 1)

    assert refill.standing(store, 1).state == refill.IDLE
    assert refill.claim(store, clock, 1)


def test_an_idle_slot_advances_to_nothing(store):
    slot = Slot(plans=[ACTIVE])

    assert refill.advance(store, Clock(), slot) == refill.Refill(slot=1)
    assert slot.ensured == []


def test_the_file_store_survives_a_restart(tmp_path):
    clock = Clock()
    refill.claim(refill.FileStore(tmp_path), clock, 3, "corp", replaced=("a", "b"))

    again = refill.FileStore(tmp_path)

    assert again.slots() == [3]
    assert refill.standing(again, 3) == refill.Refill(slot=3, state=refill.BUILDING, wargame="corp",
                                                      replaced=("a", "b"), deadline=clock.now + refill.WAIT)


def test_a_slot_emptied_while_its_refill_step_runs_stays_empty(store):
    clock = Clock()

    class EmptiedMeanwhile(Slot):
        def ensure_slot(self, wargame=""):
            refill.release(store, 1)
            return super().ensure_slot(wargame)

    refill.claim(store, clock, 1, "board", replaced=("old",))

    assert refill.advance(store, clock, EmptiedMeanwhile(plans=[BUILDING])).state == refill.IDLE
    assert refill.owed(store) == []


def test_a_slot_held_for_its_reset_is_not_ready_not_rebuilt_and_shown_running(store):
    assert refill.hold_for_refill(store, 1)
    assert refill.hold_for_refill(store, 1) is False

    assert refill.standing(store, 1).state == refill.REFILLING and refill.owed(store) == []
    assert refill.standing(store, 1).shown()["state"] == "running"
    assert refill.claim(store, Clock(), 1, "board", replaced=("old",))
