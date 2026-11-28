ROOM_REFUSAL = "range_unavailable"
READY = "idle"
SETTLING = ("running",)


def refused_for_room(status: int, codes) -> bool:
    return status == 503 and ROOM_REFUSAL in codes


def settling(slots: list[dict]) -> bool:
    return any((slot.get("refill") or {}).get("state") in SETTLING for slot in slots)
