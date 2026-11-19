import time

ROOM_REFUSAL = "range_unavailable"
READY = "idle"
SETTLING = ("running",)


def refused_for_room(status: int, codes) -> bool:
    return status == 503 and ROOM_REFUSAL in codes


def free_slots(slots: list[dict], wargame: str = "") -> list[dict]:
    return [slot for slot in slots
            if slot.get("lease") is None and (slot.get("refill") or {}).get("state") == READY
            and (not wargame or slot.get("wargame") in ("", wargame))]


def has_room(slots: list[dict], wargame: str = "") -> bool:
    return bool(free_slots(slots, wargame))


def settling(slots: list[dict]) -> bool:
    return any((slot.get("refill") or {}).get("state") in SETTLING for slot in slots)


def wait_for_room(room, seconds: float, poll: float, clock=time.monotonic, sleep=time.sleep) -> bool:
    deadline = clock() + seconds
    while not room():
        if clock() >= deadline:
            return False
        sleep(poll)
    return True


def retried(attempt, refused, make_room, attempts: int):
    result = attempt()
    for _ in range(attempts - 1):
        if not refused(result) or not make_room():
            return result
        result = attempt()
    return result
