import time

ROOM_REFUSALS = ("already open on the range", "resetting")
CAP_REFUSAL = "409 Client Error"
SETTLING = ("RESETTING", "REBUILDING", "CHECKING")


def refused_for_room(status: int, said: str) -> bool:
    return status == 409 and any(refusal in said for refusal in ROOM_REFUSALS)


def has_room(readiness: dict | None, open_sessions: int) -> bool:
    readiness = readiness or {}
    slot = readiness.get("slot") or {}
    settling = not readiness.get("ready", True) and (
        slot.get("phase") in SETTLING or (slot.get("reset") or {}).get("state") == "running"
    )
    return not settling and open_sessions < int(readiness.get("max_sessions") or 1)


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
