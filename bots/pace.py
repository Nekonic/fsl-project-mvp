from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

TERMINAL_GRANTS = frozenset({"attack_terminal", "defence_waf_terminal", "defence_ids_terminal"})
NEVER_PACED = frozenset({"attack_forfeit", "defence_forfeit", "allocation_heartbeat"})


@dataclass(frozen=True)
class Pace:
    per_window: int
    window_s: float
    min_gap_s: float

    @classmethod
    def of(cls, given: Mapping) -> Pace:
        return cls(per_window=int(given["per_window"]), window_s=float(given["window_s"]),
                   min_gap_s=float(given["min_gap_s"]))


def counted(method: str, operation: str | None) -> bool:
    if operation in NEVER_PACED:
        return False
    return method.upper() != "GET" or operation in TERMINAL_GRANTS


def pace_wait(now: float, recent: Iterable[float], pace: Pace) -> float | None:
    inside = sorted(at for at in recent if now - at < pace.window_s)
    waits = [inside[-1] + pace.min_gap_s - now] if inside else []
    if len(inside) >= pace.per_window:
        waits.append(inside[-pace.per_window] + pace.window_s - now)
    longest = max(waits, default=0.0)
    return longest if longest > 0 else None
