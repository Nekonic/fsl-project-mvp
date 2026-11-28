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
    only = {"test_board", "test_pvp", "test_geoip_durable"}
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
    assert "board_round" in shared["test_board_loot"]
    assert shared["test_window_correlation"] == shared["test_strategy_comparison"] == {"terminal_windows"}
    assert not shared["test_concurrent_rounds"], (
        "a helper's argument was read as the red-team fixture"
    )


def test_the_red_team_run_is_read_from_what_its_fixture_recorded():
    readers = [path.name for path in (ROOT / "test").glob("test_*.py")
               if 'full_run["round"]' in path.read_text()]

    assert "round" not in split.shared_fixtures(), (
        "a test that asks the platform about the red-team round hours after its allocation closed finds it "
        "deleted by CR_RETAIN_CLOSED_MINUTES; full_run records what the tests read when it runs"
    )
    assert not readers, readers


@pytest.mark.parametrize("workers", [2, 3, 4])
def test_the_modules_that_hold_two_sessions_take_two_slots_and_start_first(workers):
    _, waiting = split.plan(workers)

    holding = [p for p in waiting if set(p.modules) & set(split.TWO_ALLOCATIONS)]
    assert holding and all(p.slots == 2 for p in holding)
    assert waiting[:len(holding)] == holding, (
        "a two-slot group queued behind one-slot groups waits until two slots are free at once, "
        "which may not happen before the end of the run"
    )
    assert all(p.slots == 1 for p in waiting if p not in holding)


def test_a_group_starts_only_when_the_slots_it_holds_are_free():
    two = split.Process("group 1", "worker", ["test_concurrent_rounds"], 90, 2)
    one = split.Process("group 2", "worker", ["test_board"], 30, 1)

    assert split.next_to_start([two, one], 2) is two
    assert split.next_to_start([two, one], 1) is one
    assert split.next_to_start([two, one], 0) is None


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
        for touch in ("plays.", "/api/", "run(", "from_attacker", "standing_stack"):
            assert touch not in source, (
                f"{module} runs while a range reset is in progress, and it {touch!r}"
            )


def test_the_worker_count_is_the_number_of_slots_the_range_has(monkeypatch):
    monkeypatch.setattr(split, "_slots", lambda platform: [slot(), slot(allocation=3)])
    assert split.workers_the_range_allows("http://platform") == 2

    def unreachable(platform):
        raise OSError("connection refused")

    monkeypatch.setattr(split, "_slots", unreachable)
    assert split.workers_the_range_allows("http://platform") == 1


def test_a_refusal_for_want_of_room_is_told_apart_from_any_other():
    assert opening.refused_for_room(503, ["range_unavailable"])
    assert not opening.refused_for_room(503, ["sensor_unavailable"])
    assert not opening.refused_for_room(409, ["range_unavailable"])
    assert not opening.refused_for_room(409, ["allocation_closed"])


def slot(allocation=None, state="idle", wargame="board"):
    return {"slot": 1, "wargame": wargame, "allocation": allocation, "refill": {"state": state, "reason": ""}}


def test_a_slot_whose_refill_runs_is_settling():
    assert opening.settling([slot(), slot(state="running")]) and not opening.settling([slot(state="failed")])
    assert not opening.settling([])


def test_the_run_never_holds_more_slots_than_the_range_has(monkeypatch, tmp_path):
    in_flight, most = [], []

    class Finishing:
        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1
            return 0 if self.polls > 2 else None

    def started(process, slots, logs, extra):
        in_flight.append(process.slots)
        most.append(sum(in_flight))
        return process, Finishing(), None, None

    def finished(process, running, log, report):
        in_flight.remove(process.slots)
        return 0, split.Totals(passed=1)

    monkeypatch.setattr(split, "_started", started)
    monkeypatch.setattr(split, "_finished", finished)
    monkeypatch.setattr(split, "POLL_SECONDS", 0)
    groups = [split.Process(f"group {n}", "worker", [f"test_{n}"], 10, slots)
              for n, slots in enumerate([2, 1, 1, 1, 1, 2, 1])]

    codes, totals = split.run_all([], groups, 3, tmp_path, [])

    assert codes == [0] * len(groups) and totals.passed == len(groups)
    assert max(most) <= 3


def test_a_group_wider_than_the_range_fails_the_run_instead_of_waiting_forever(monkeypatch, tmp_path):
    codes, totals = split.run_all([], [split.Process("group 1", "worker", ["test_x"], 10, 2)], 1, tmp_path, [])

    assert codes == [1] and totals.errors == 1


def test_a_run_over_an_hour_is_stopped_and_reported_as_an_error(monkeypatch, tmp_path, capsys):
    killed = []

    class Hanging:
        def poll(self):
            return None

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(split, "_started", lambda process, slots, logs, extra: (process, Hanging(), None, None))
    monkeypatch.setattr(split, "POLL_SECONDS", 0)
    ticks = iter([0, 10, split.LONGEST_RUN_SECONDS + 1])

    codes, totals = split.run_all([split.Process("group 1", "worker", ["test_x"])], [], 1, tmp_path, [],
                                  clock=lambda: next(ticks))

    assert codes == [1] and totals.errors == 1 and killed == [True]
    assert split.OVER_AN_HOUR in capsys.readouterr().out


def test_the_whole_suite_refuses_to_start_unless_it_is_the_final_check(monkeypatch, capsys):
    monkeypatch.delenv("CR_FINAL_CHECK", raising=False)

    assert split.main([]) == 2
    assert "CR_FINAL_CHECK=1" in capsys.readouterr().out


def test_the_lock_names_the_run_while_it_runs_and_is_gone_after(tmp_path):
    lock = tmp_path / "acceptance.lock"

    with split.held_lock("test_x", "http://platform", lock) as held:
        assert '"modules": "test_x"' in held.read_text()

    assert not lock.exists()
