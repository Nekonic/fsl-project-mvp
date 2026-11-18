from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.http import JsonResponse

from range import substrate
from range.ports import RangeUnavailable

TTL = 30.0

_cached: tuple[float, frozenset[str]] = (0.0, frozenset())
_refreshing = threading.Lock()

def _fresh() -> frozenset[str] | None:
    age, known = _cached
    return known if age and time.monotonic() - age < TTL else None

def scored_hosts() -> frozenset[str]:
    known = _fresh()
    if known is not None:
        return known
    with _refreshing:
        known = _fresh()
        return known if known is not None else _read()

def _read() -> frozenset[str]:
    global _cached

    adapter = substrate()
    slots = adapter.every_slot() if hasattr(adapter, "every_slot") else [adapter]
    with ThreadPoolExecutor(max_workers=len(slots), thread_name_prefix="cr-reach") as pool:
        read = list(pool.map(_segments_of, slots))

    scorer = settings.RANGE.roles.get("scorer") or ""
    known = frozenset(
        node.address
        for segments in read
        for segment in segments
        for node in segment.nodes
        if node.address and node.name != scorer
    )
    _cached = (time.monotonic(), known)
    return known

def _segments_of(one) -> tuple:
    try:
        return tuple(one.segments())
    except RangeUnavailable:
        return ()

def not_from_inside_the_range(get_response):
    def middleware(request):
        address = request.META.get("REMOTE_ADDR") or ""
        if address in scored_hosts():
            return JsonResponse(
                {
                    "detail": (
                        f"{address} is a host in the range; the platform "
                        "refuses requests from scored hosts"
                    )
                },
                status=403,
            )
        return get_response(request)

    return middleware
