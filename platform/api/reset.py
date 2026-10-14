import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from range.ports import Drifted, RangeUnavailable

RESET_WAIT = 1800
RESET_POLL = 2.0
REBUILD_SHOWN = 120

IDLE = "idle"
RUNNING = "running"
FAILED = "failed"

_guard = threading.Lock()
_states: dict[int, dict] = {}

def _of(slot: int) -> dict:
    return _states.setdefault(slot, {"state": IDLE, "reason": ""})

def standing(slot: int = 1) -> dict:
    with _guard:
        return dict(_of(slot))

def configured_by_hand(slot: int = 1) -> None:
    with _guard:
        if _of(slot)["state"] == FAILED:
            _of(slot).update(state=IDLE, reason="")

def claim(slot: int) -> bool:
    with _guard:
        if _of(slot)["state"] == RUNNING:
            return False
        _of(slot).update(state=RUNNING, reason="")
        return True

def release(slot: int) -> None:
    _set(slot, IDLE, "")

def begin(adapter, turn, rebuilt=None, claimed=False, then=None):
    slot = getattr(adapter, "slot", 1)
    if not claimed and not claim(slot):
        return None
    worker = threading.Thread(
        target=_reset, args=(adapter, turn, rebuilt, then), name=f"fsl-range-reset-{slot}", daemon=True
    )
    worker.start()
    return worker

def _set(slot: int, state: str, reason: str) -> None:
    with _guard:
        _of(slot).update(state=state, reason=reason)

def _reset(adapter, turn, rebuilt, then=None) -> None:
    slot = getattr(adapter, "slot", 1)
    deadline = time.monotonic() + RESET_WAIT
    servers = None if rebuilt is None else {server for _, server in rebuilt}
    try:
        if hasattr(adapter, "reset_in_place"):
            hosts = [host for host, _ in rebuilt or ()]
            with turn:
                _side_by_side(
                    lambda: _until_answered(adapter.reset_in_place, deadline),
                    lambda: _configure_once_active(
                        adapter, deadline, servers, lambda: adapter.configure_rebuilt(hosts)),
                )
        else:
            _configure_once_active(adapter, deadline, servers,
                                   lambda: _holding(turn, adapter.configure_slot))
    except Exception as exc:
        _set(slot, FAILED, str(exc) or type(exc).__name__)
    else:
        _set(slot, IDLE, "")
        if then is not None:
            then()

def _holding(turn, step):
    with turn:
        return step()

def _side_by_side(*steps) -> None:
    with ThreadPoolExecutor(max_workers=len(steps), thread_name_prefix="fsl-range-reset") as pool:
        running = [pool.submit(step) for step in steps]
        wait(running)
    for done in running:
        done.result()

def _configure_once_active(adapter, deadline: float, servers, configure) -> None:
    shown = time.monotonic() + REBUILD_SHOWN
    left_active: set[str] = set()
    while not _rebuilt(adapter, servers, left_active, shown):
        _pause_before(deadline, f"the slot's VMs were not all ACTIVE within {RESET_WAIT}s")
    _until_answered(configure, deadline)

def _until_answered(step, deadline: float):
    while True:
        try:
            return step()
        except RangeUnavailable as exc:
            _pause_before(deadline, f"configure did not reach the slot within {RESET_WAIT}s: {exc}")

def _rebuilt(adapter, servers, left_active: set[str], shown: float) -> bool:
    try:
        plan = adapter.plan_slot()
    except RangeUnavailable:
        return False
    if plan.boot or plan.blocked:
        raise Drifted("; ".join(plan.blocked) or f"{', '.join(plan.boot)} is not standing")
    left_active.update(server for _, server, status in plan.standing if status != "ACTIVE")
    unseen = [host for host, server, _ in plan.standing
              if (servers is None or server in servers) and server not in left_active]
    if unseen and time.monotonic() >= shown:
        raise Drifted(
            f"Nova never showed {', '.join(unseen)} rebuilding within {REBUILD_SHOWN}s, "
            f"so the slot was not configured in case it is the VM from before the rebuild"
        )
    return plan.active and not unseen

def _pause_before(deadline: float, gave_up: str) -> None:
    if time.monotonic() >= deadline:
        raise Drifted(gave_up)
    time.sleep(RESET_POLL)
