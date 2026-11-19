from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from domain.types import Charge, HpRule, OriginState

BURST_MEMORY_S = 300


@dataclass(frozen=True)
class LedgerState:
    origins: tuple[OriginState, ...]
    per_second: tuple[tuple[str, int, int], ...] = ()
    charged_markers: frozenset[str] = frozenset()

    @property
    def origins_left(self) -> int:
        return sum(1 for origin in self.origins if not origin.spent)

    @property
    def spent_ips(self) -> tuple[str, ...]:
        return tuple(origin.ip for origin in self.origins if origin.spent)


def opened(origins: Sequence[tuple[str, str, str]], rule: HpRule) -> LedgerState:
    return LedgerState(
        origins=tuple(
            OriginState(origin_id=origin_id, ip=ip, label=label, budget=rule.budget, left=rule.budget)
            for origin_id, ip, label in origins
        )
    )


def cost(rule: HpRule, refused: bool, in_burst: bool) -> int:
    return rule.per_request * (rule.refused_x if refused else 1) * (rule.burst_x if in_burst else 1)


def debit(state: LedgerState, charges: Sequence[Charge], rule: HpRule) -> tuple[LedgerState, tuple[OriginState, ...]]:
    origins = {origin.ip: origin for origin in state.origins}
    counts = {(ip, second): n for ip, second, n in state.per_second}
    markers = set(state.charged_markers) | {c.marker for c in charges if c.synchronous and c.marker is not None}
    newly_spent: list[OriginState] = []

    for charge in sorted(charges, key=lambda c: c.at):
        if not charge.synchronous and charge.marker is not None and charge.marker in markers:
            continue
        origin = origins.get(charge.origin_ip)
        if origin is None or origin.spent:
            continue
        bucket = (charge.origin_ip, int(charge.at.timestamp()))
        counts[bucket] = counts.get(bucket, 0) + 1
        left = origin.left - cost(rule, charge.refused, counts[bucket] > rule.burst_per_s)
        origin = replace(origin, left=left, spent_at=charge.at if left <= 0 else None)
        origins[charge.origin_ip] = origin
        if origin.spent:
            newly_spent.append(origin)

    return (
        LedgerState(
            origins=tuple(origins[origin.ip] for origin in state.origins),
            per_second=_recent(counts),
            charged_markers=frozenset(markers),
        ),
        tuple(newly_spent),
    )


def spend(state: LedgerState, ip: str, at: datetime) -> tuple[LedgerState, OriginState | None]:
    target = next((origin for origin in state.origins if origin.ip == ip and not origin.spent), None)
    if target is None:
        return state, None
    spent = replace(target, spent_at=at)
    return replace(state, origins=tuple(spent if origin is target else origin for origin in state.origins)), spent


def next_origin(state: LedgerState) -> OriginState | None:
    return next((origin for origin in state.origins if not origin.spent), None)


def _recent(counts: dict[tuple[str, int], int]) -> tuple[tuple[str, int, int], ...]:
    if not counts:
        return ()
    newest = max(second for _, second in counts)
    return tuple(
        (ip, second, n) for (ip, second), n in sorted(counts.items()) if second > newest - BURST_MEMORY_S
    )
