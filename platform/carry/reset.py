import threading
import time
from pathlib import Path

from django.conf import settings

from range.ports import Drifted, RangeUnavailable

RESET_WAIT = 1800
RESET_POLL = 5.0

IDLE = "idle"
RUNNING = "running"
FAILED = "failed"

_guard = threading.Lock()
_states: dict[int, dict] = {}

def _marker(slot: int) -> Path:
    return Path(settings.RESET_OWED_DIR) / f"slot-{slot}"

def owed() -> list[int]:
    directory = Path(settings.RESET_OWED_DIR)
    if not directory.is_dir():
        return []
    return sorted(int(path.name.removeprefix("slot-")) for path in directory.glob("slot-*"))

def wanted(slot: int) -> str:
    try:
        return _marker(slot).read_text().strip()
    except OSError:
        return ""

def _of(slot: int) -> dict:
    return _states.setdefault(slot, {"state": IDLE, "reason": ""})

def standing(slot: int = 1) -> dict:
    with _guard:
        return dict(_of(slot))

def configured_by_hand(slot: int = 1) -> None:
    with _guard:
        if _of(slot)["state"] == FAILED:
            _of(slot).update(state=IDLE, reason="")
        if _of(slot)["state"] == IDLE:
            _marker(slot).unlink(missing_ok=True)

def claim(slot: int, wargame: str = "") -> bool:
    with _guard:
        if _of(slot)["state"] == RUNNING:
            return False
        _marker(slot).parent.mkdir(parents=True, exist_ok=True)
        _marker(slot).write_text(wargame)
        _of(slot).update(state=RUNNING, reason="")
        return True

def release(slot: int) -> None:
    _set(slot, IDLE, "")

def failed(slot: int, reason: str) -> None:
    _set(slot, FAILED, reason)

def begin(adapter, turn, rebuilt=None, claimed=False, then=None, wargame=""):
    slot = getattr(adapter, "slot", 1)
    if not claimed and not claim(slot, wargame):
        return None
    worker = threading.Thread(
        target=_refill, args=(adapter, turn, rebuilt, then, wargame), name=f"cr-slot-refill-{slot}",
        daemon=True,
    )
    worker.start()
    return worker

def _set(slot: int, state: str, reason: str) -> None:
    with _guard:
        _of(slot).update(state=state, reason=reason)
        if state == IDLE:
            _marker(slot).unlink(missing_ok=True)

def _refill(adapter, turn, rebuilt, then=None, wargame="") -> None:
    slot = getattr(adapter, "slot", 1)
    deadline = time.monotonic() + RESET_WAIT
    gone = {stack for _, stack in rebuilt or ()}
    try:
        while not _refilled(adapter, turn, gone, wargame):
            _pause_before(deadline, f"slot {slot}'s stack was not created and set up within {RESET_WAIT}s")
        _until_answered(lambda: _holding(turn, adapter.configure_slot), deadline)
    except Exception as exc:
        _set(slot, FAILED, str(exc) or type(exc).__name__)
    else:
        _set(slot, IDLE, "")
        if then is not None:
            then()

def _refilled(adapter, turn, gone: set[str], wargame: str) -> bool:
    try:
        with turn:
            plan = adapter.ensure_slot(wargame=wargame)
    except RangeUnavailable:
        return False
    if plan.failures:
        raise Drifted("; ".join(plan.failures))
    return plan.active and plan.stack_id not in gone

def _holding(turn, step):
    with turn:
        return step()

def _until_answered(step, deadline: float):
    while True:
        try:
            return step()
        except RangeUnavailable as exc:
            _pause_before(deadline, f"configure did not reach the slot within {RESET_WAIT}s: {exc}")

def _pause_before(deadline: float, gave_up: str) -> None:
    if time.monotonic() >= deadline:
        raise Drifted(gave_up)
    time.sleep(RESET_POLL)
