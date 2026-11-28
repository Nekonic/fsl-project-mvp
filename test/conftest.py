import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import plays
import range as the_range
from bots import signin
from opening import settling
from range import ATTACKER, run, start_hint

pytest_plugins = ["shared_rounds"]

REPO_ROOT = plays.REPO_ROOT
PLATFORM_URL = plays.PLATFORM_URL
TARGET_PUBLIC = "http://board.com"
REFILL_WAIT = 1800
RESET_POLL = 2

SPLIT = os.environ.get("CR_SPLIT", "")
IDLE = SPLIT == "idle"
BESIDE_ANOTHER_WORKER = SPLIT == "worker" and int(os.environ.get("CR_WORKERS") or 1) > 1


def reachable() -> bool:
    try:
        return plays.ask("auth_csrf", signin.anonymous(PLATFORM_URL, 30)).ok
    except requests.RequestException:
        return False


def wait_out_a_refill() -> list[dict]:
    deadline = time.monotonic() + REFILL_WAIT
    while True:
        slots = plays.slots()
        if (slots and not settling(slots)) or time.monotonic() >= deadline:
            return slots
        time.sleep(RESET_POLL)


def listed_for_pruning(played: plays.Played) -> None:
    listed = os.environ.get("CR_ACCEPTANCE_ALLOCATIONS")
    if listed:
        with open(listed, "a", encoding="utf-8") as ids:
            ids.write(f"{played.allocation}\n")


plays.LISTENERS.append(listed_for_pruning)


@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    assert reachable(), f"could not reach {PLATFORM_URL}. Run `{start_hint()}` first."
    if IDLE:
        return
    slots = wait_out_a_refill()
    assert slots, f"{PLATFORM_URL}/api/staff/range/ lists no slot. Run `{start_hint()}` first."
    assert not settling(slots), f"the range was still refilling a slot after {REFILL_WAIT}s: {slots}"


class Standing:
    def __init__(self):
        self.played: plays.Played | None = None

    def allocation(self) -> int | None:
        if not BESIDE_ANOTHER_WORKER:
            return None
        held = [played.allocation for played in plays.OPENED if not played.closed and played is not self.played]
        assert not held, (
            f"a range call named no allocation while allocation {held} is open; beside another worker the newest "
            f"slot is not this test's, so pass allocation= explicitly")
        if self.played is None or self.played.closed:
            self.played = plays.play("board")
        return self.played.allocation

    def release(self) -> None:
        if self.played is not None:
            plays.close(self.played)
        self.played = None


STANDING = Standing()
if BESIDE_ANOTHER_WORKER:
    the_range.default_to(STANDING.allocation)


@pytest.fixture
def standing_stack(stack_is_up):
    return STANDING.allocation()


def close_opened_since(count: int) -> None:
    for played in plays.OPENED[count:]:
        if played is not STANDING.played:
            plays.close(played)


@pytest.fixture(scope="session", autouse=True)
def the_run_leaves_no_allocation_open(stack_is_up):
    yield
    STANDING.release()
    for played in plays.OPENED:
        plays.close(played)


@pytest.fixture(scope="module", autouse=True)
def a_module_closes_the_allocations_it_opened(the_run_leaves_no_allocation_open):
    count = len(plays.OPENED)
    yield
    close_opened_since(count)


@pytest.fixture(autouse=True)
def the_range_is_not_refilling(stack_is_up):
    if not IDLE and not BESIDE_ANOTHER_WORKER:
        slots = wait_out_a_refill()
        assert not settling(slots), (
            f"the range was still refilling after {REFILL_WAIT}s: {slots}. A closed allocation refills its slot's "
            f"stack, and a test that reaches a host meanwhile finds it gone or half configured")


@pytest.fixture(autouse=True)
def a_test_closes_the_allocations_it_opened(the_run_leaves_no_allocation_open):
    count = len(plays.OPENED)
    yield
    close_opened_since(count)


def target_code(path: str = "/", allocation: int | None = None) -> int:
    probe = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
                           f"{TARGET_PUBLIC}{path}"], allocation=allocation)
    code = probe.stdout.strip()
    return int(code) if code.isdigit() else 0


def from_attacker(path: str, allocation: int | None = None) -> None:
    result = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "--max-time", "20", f"{TARGET_PUBLIC}{path}"],
                 allocation=allocation)
    assert result.ok, f"could not reach the target from the attacker box: {result.stderr}"


def runs_the_declared_rules(played: plays.Played) -> str:
    committed = plays.declared_rules(played.wargame)
    live = plays.ids_rules(played)["text"]

    assert live == committed, (
        f"round {played.round} started with a sensor that is not running the rule set this repo declares. A test "
        f"that captures 'whatever was there' and restores it would cement somebody else's leftovers as the "
        f"baseline.")
    return committed
