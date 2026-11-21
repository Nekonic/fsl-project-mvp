from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sandbox.runner import RangeUnavailable

TTL = 30.0


class ScoredHosts:
    def __init__(self, adapter, scorer: str = "", ttl: float = TTL, clock: Callable[[], float] = time.monotonic):
        self.adapter = adapter
        self.scorer = scorer
        self.ttl = ttl
        self.clock = clock
        self._cached: tuple[float, frozenset[str]] | None = None
        self._refreshing = threading.Lock()

    def _fresh(self) -> frozenset[str] | None:
        if self._cached is None:
            return None
        read_at, known = self._cached
        return known if self.clock() - read_at < self.ttl else None

    def known(self) -> frozenset[str]:
        found = self._fresh()
        if found is not None:
            return found
        with self._refreshing:
            found = self._fresh()
            if found is None:
                found = addresses(self.adapter, self.scorer)
                self._cached = (self.clock(), found)
            return found

    def refuses(self, address: str) -> bool:
        return bool(address) and address in self.known()


def addresses(adapter, scorer: str = "") -> frozenset[str]:
    slots = adapter.every_slot() if hasattr(adapter, "every_slot") else [adapter]
    with ThreadPoolExecutor(max_workers=max(1, len(slots)), thread_name_prefix="cr-reach") as pool:
        read = list(pool.map(_segments_of, slots))
    return frozenset(
        node.address
        for segments in read
        for segment in segments
        for node in segment.nodes
        if node.address and node.name != scorer
    )


def _segments_of(one) -> tuple:
    try:
        return tuple(one.segments())
    except RangeUnavailable:
        return ()
