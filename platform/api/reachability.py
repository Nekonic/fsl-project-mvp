from __future__ import annotations

import time

from django.conf import settings
from django.http import JsonResponse

from range import substrate
from range.ports import RangeUnavailable

TTL = 30.0

_cached: tuple[float, frozenset[str]] = (0.0, frozenset())

def scored_hosts() -> frozenset[str]:
    global _cached

    age, known = _cached
    if time.monotonic() - age < TTL:
        return known

    try:
        described = substrate().describe()
    except RangeUnavailable:
        _cached = (time.monotonic(), frozenset())
        return frozenset()

    scorer = settings.RANGE.roles.get("scorer") or ""
    known = frozenset(
        node.address
        for segment in described.segments
        for node in segment.nodes
        if node.address and node.name != scorer
    )
    _cached = (time.monotonic(), known)
    return known

def forget() -> None:
    global _cached

    _cached = (0.0, frozenset())

def not_from_inside_the_range(get_response):
    def middleware(request):
        if (request.META.get("REMOTE_ADDR") or "") in scored_hosts():
            return JsonResponse(
                {
                    "detail": (
                        "this address stands inside the range, and the range "
                        "does not answer the party it is scoring"
                    )
                },
                status=403,
            )
        return get_response(request)

    return middleware
