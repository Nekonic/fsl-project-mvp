from __future__ import annotations

import math
from collections.abc import Mapping

DEFAULT_RATE = 1.0
FLOOR_FACTOR = 2


def allocated(weights: Mapping[str, float], total: int) -> list[str]:
    whole = sum(weights.values())
    shares = {origin: total * weight / whole for origin, weight in weights.items()}
    counts = {origin: int(share) for origin, share in shares.items()}
    for origin in sorted(shares, key=lambda one: (counts[one] - shares[one], one))[:total - sum(counts.values())]:
        counts[origin] += 1
    return [origin for origin in sorted(weights, key=lambda one: (-weights[one], one)) for _ in range(counts[origin])]


def rate_of(declared: Mapping) -> float:
    return float(declared.get("rate") or DEFAULT_RATE)


def busiest_per_minute(declared: Mapping) -> float:
    weights = {origin: weight for origin, weight in (declared.get("origins") or {}).items() if weight > 0}
    users = int(declared.get("users") or 0)
    if not weights or users <= 0:
        return 0.0
    homes = allocated(weights, users)
    most = max(homes.count(origin) for origin in set(homes))
    return rate_of(declared) * 60 * most / users


def limit_floor(declared: Mapping) -> int:
    return math.ceil(FLOOR_FACTOR * busiest_per_minute(declared))
