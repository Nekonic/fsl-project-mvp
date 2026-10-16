import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    loader = SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = module
    loader.exec_module(module)
    return module


split = load("acceptance_split", ROOT / "bin/acceptance")
opening = load("acceptance_opening", ROOT / "test/opening.py")


def processes(workers):
    together, after = split.plan(workers)
    return together + after


@pytest.mark.parametrize("workers", [1, 2, 3, 4])
def test_every_module_runs_in_exactly_one_process(workers):
    ran = [module for process in processes(workers) for module in process.modules]

    assert sorted(ran) == split.modules(), (
        "a module ran twice or not at all, so the split run is not the suite"
    )


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_a_run_limited_to_some_modules_plans_those_and_no_others(workers):
    only = {"test_board", "test_lesson", "test_geoip_durable"}
    together, after = split.plan(workers, only=only)

    ran = [module for process in together + after for module in process.modules]

    assert sorted(ran) == sorted(only), (
        f"bin/verify --changed --live asked for {sorted(only)} and the split planned {sorted(ran)}"
    )


@pytest.mark.parametrize("workers", [2, 3, 4])
def test_modules_sharing_a_session_fixture_run_in_one_process(workers):
    where = {module: process.name for process in processes(workers) for module in process.modules}
    users = {}
    for module, shared in split.shared_by_module().items():
        for fixture in shared:
            users.setdefault(fixture, set()).add(where[module])

    split_up = {fixture: names for fixture, names in users.items() if len(names) > 1}
    assert not split_up, (
        f"a shared session was opened once per process instead of once: {split_up}"
    )


def test_the_red_team_run_is_shared_by_the_modules_that_read_it():
    shared = split.shared_by_module()

    assert "full_run" in shared["test_acceptance"]
    assert "full_run" in shared["test_strategy_honesty"]
    assert "board_session" in shared["test_board_loot"]
    assert not shared["test_window_correlation"], (
        "a helper's session_id argument was read as the red-team fixture"
    )


@pytest.mark.parametrize("workers", [2, 3])
def test_the_modules_that_hold_two_sessions_run_alone_after_the_rest(workers):
    together, after = split.plan(workers)

    assert not {m for p in together for m in p.modules} & set(split.SOLO)
    assert [p.modules for p in after] == [sorted(split.SOLO)]


@pytest.mark.parametrize("workers", [2, 3])
def test_the_checks_that_need_a_standing_stack_share_one_and_go_first(workers):
    holding = [p for p in processes(workers) if set(p.modules) & set(split.STANDING_STACK)]

    assert len(holding) == 1, "each worker opened a session of its own for them"
    first = holding[0].modules[:len(split.STANDING_STACK)]
    assert sorted(first) == sorted(split.STANDING_STACK)


def test_the_idle_modules_ask_for_no_session_and_touch_no_host():
    shared = split.shared_by_module()
    for module in split.IDLE:
        source = (split.TESTS / f"{module}.py").read_text()
        assert not shared[module], module
        for touch in ("/api/sessions/", "run(", "from_attacker", "standing_stack", "segments("):
            assert touch not in source, (
                f"{module} runs while a range reset is in progress, and it {touch!r}"
            )


def test_the_worker_count_is_what_the_range_lets_open_at_once(monkeypatch):
    monkeypatch.setattr(split, "_ask", lambda platform, path: {"max_sessions": 2})
    assert split.workers_the_range_allows("http://platform") == 2

    def unreachable(platform, path):
        raise OSError("connection refused")

    monkeypatch.setattr(split, "_ask", unreachable)
    assert split.workers_the_range_allows("http://platform") == 1


def test_a_refusal_for_want_of_room_is_told_apart_from_any_other():
    assert opening.refused_for_room(409, "2 sessions are already open on the range; close one first")
    assert opening.refused_for_room(409, "the range is not ready: the slot is resetting")
    assert not opening.refused_for_room(409, "the range is not ready: the target's ground truth could not be read")
    assert not opening.refused_for_room(503, "already open on the range")


def test_room_means_a_free_session_on_a_range_that_has_settled():
    assert opening.has_room({"ready": True, "max_sessions": 2}, 1)
    assert not opening.has_room({"ready": True, "max_sessions": 2}, 2)
    for phase in ("RESETTING", "REBUILDING", "CHECKING"):
        assert not opening.has_room({"ready": False, "max_sessions": 2, "slot": {"phase": phase}}, 0)
    assert not opening.has_room({"ready": False, "slot": {"reset": {"state": "running"}}}, 0)
    assert opening.has_room({"ready": False, "slot": {"phase": "NOT_STANDING"}}, 0), (
        "a range that will not come up by itself is waited on for half an hour"
    )
    assert opening.has_room({}, 0) and not opening.has_room({}, 1)


def test_waiting_for_room_polls_until_there_is_some_or_time_is_up():
    now = [0.0]
    answers = iter([False, False, True])

    def sleep(seconds):
        now[0] += seconds

    assert opening.wait_for_room(lambda: next(answers), 60, 5, lambda: now[0], sleep)
    assert now[0] == 10
    assert not opening.wait_for_room(lambda: False, 12, 5, lambda: now[0], sleep)


def test_an_open_refused_for_room_is_retried_once_there_is_room():
    answers = iter(["409", "409", "201"])
    made_room = []

    result = opening.retried(lambda: next(answers), lambda said: said == "409",
                             lambda: made_room.append(1) or True, attempts=5)

    assert result == "201" and len(made_room) == 2
    assert opening.retried(lambda: "409", lambda said: True, lambda: False, attempts=5) == "409"
    tries = []
    opening.retried(lambda: tries.append(1) or "409", lambda said: True, lambda: True, attempts=3)
    assert len(tries) == 3


def test_a_red_team_run_refused_for_want_of_room_is_told_apart_from_any_other_refusal():
    lost_the_slot = ("requests.exceptions.HTTPError: 409 Client Error: Conflict for url: "
                     "http://localhost:8000/api/sessions/: {\"detail\": \"the range is not ready: "
                     "slot 2: the range is resetting after the last session closed\"}")
    assert opening.refused_a_run_for_room(lost_the_slot)
    assert opening.refused_a_run_for_room(
        "409 Client Error: Conflict: {\"detail\": \"2 sessions are already open on the range; close one first\"}")
    assert not opening.refused_a_run_for_room(
        "409 Client Error: Conflict: {\"detail\": \"fsl-edge did not take its configuration\"}"), (
        "a range that refused for a reason other than room is retried for half an hour"
    )
    assert not opening.refused_a_run_for_room("503 Server Error: already open on the range")
