from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

DEFAULT_WATCH_S = 30.0
ENDED = "ended"
LINES_MAX = 20
ALERT_PAGES_MAX = 5
ALERT_FIELDS = ("id", "time", "engine", "rule", "signature", "src_ip", "uri", "blocked")

Read = Callable[[str, dict], Mapping]


@dataclass
class Seen:
    phase: str | None
    alerts_after: int = 0
    traffic_after: str = ""
    addresses: set[str] = field(default_factory=set)
    origins: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class Feed:
    phase: str | None
    phase_changed: bool
    end_reason: str
    alerts: tuple[dict, ...]
    origins: tuple[dict, ...]
    new_addresses: frozenset[str]

    @property
    def ended(self) -> bool:
        return self.phase == ENDED

    @property
    def news(self) -> bool:
        return (self.ended or self.phase_changed or bool(self.alerts) or bool(self.new_addresses)
                or any(origin["refused"] for origin in self.origins))


def interval_of(claimed: Mapping) -> float:
    given = claimed.get("watch_s")
    return float(given) if given else DEFAULT_WATCH_S


def new_alerts(read: Read, after: int) -> tuple[list[dict], int]:
    found: list[dict] = []
    for _ in range(ALERT_PAGES_MAX):
        page = read("defence_alerts", {"after": after})
        rows = [row for row in page.get("alerts") or [] if int(row.get("id") or 0) > after]
        moved = int(page.get("next") or after)
        found.extend(rows)
        if not rows or moved <= after:
            break
        after = moved
    return found, after


def merged(origins: dict[str, dict], lines) -> None:
    for line in lines:
        if not isinstance(line, Mapping) or not line.get("ip"):
            continue
        held = origins.setdefault(line["ip"], {"ip": line["ip"], "requests": 0, "refused": 0, "last_at": None})
        held["requests"] += int(line.get("requests") or 0)
        held["refused"] += int(line.get("refused") or 0)
        if line.get("last_at") and (held["last_at"] is None or line["last_at"] > held["last_at"]):
            held["last_at"] = line["last_at"]


def busiest_first(origins) -> list[dict]:
    return sorted(origins, key=lambda origin: (-origin["refused"], -origin["requests"], origin["ip"]))


def listed(kind: str, rows: list[dict], more_hint: str) -> list[str]:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows[:LINES_MAX]]
    if len(rows) > LINES_MAX:
        lines.append(f"... and {len(rows) - LINES_MAX} more {kind} not listed here ({more_hint}).")
    return lines


def feed_text(feed: Feed, seen: Seen) -> str:
    parts = []
    if feed.ended:
        parts.append(f"The round has ended (end_reason {feed.end_reason or 'none'}). Read round_score until "
                     f"pending is false, then stop; no further feeds will come.")
    elif feed.phase_changed:
        parts.append(f"The phase is now {feed.phase}.")
    if feed.alerts:
        parts.append(f"{len(feed.alerts)} new alerts since the last feed:")
        parts.extend(listed("alerts", [{key: alert.get(key) for key in ALERT_FIELDS} for alert in feed.alerts],
                            f"read defence_alerts; the next cursor is now {seen.alerts_after}"))
    else:
        parts.append("No new alerts since the last feed.")
    if feed.origins:
        if feed.new_addresses:
            parts.append(f"Source addresses not seen before: {', '.join(sorted(feed.new_addresses))}.")
        parts.append("Requests and refusals per source address since the last feed:")
        parts.extend(listed("addresses", busiest_first(feed.origins), "read defence_traffic"))
    return "\n".join(parts)


class Watch:
    def __init__(self, read: Read, say: Callable[[str], None], close: Callable[[], None], phase: str | None):
        self.read = read
        self.say = say
        self.close = close
        self.seen = Seen(phase=phase)
        self.idle = False
        self.closed = False
        self.lock = threading.Lock()

    def turn_ended(self) -> None:
        with self.lock:
            self.idle = True

    def stop(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.close()

    def gathered(self, state: Mapping) -> Feed:
        seen = self.seen
        phase = state.get("phase")
        alerts, seen.alerts_after = new_alerts(self.read, seen.alerts_after)
        traffic = self.read("defence_traffic", {"after": seen.traffic_after})
        seen.traffic_after = str(traffic.get("next") or seen.traffic_after)
        merged(seen.origins, traffic.get("by_origin") or [])
        changed = phase != seen.phase
        seen.phase = phase
        return Feed(phase=phase, phase_changed=changed, end_reason=str(state.get("end_reason") or ""),
                    alerts=tuple(alerts), origins=tuple(seen.origins.values()),
                    new_addresses=frozenset(seen.origins) - seen.addresses)

    def sent(self, feed: Feed) -> None:
        with self.lock:
            self.idle = False
        self.say(feed_text(feed, self.seen))
        self.seen.addresses |= set(self.seen.origins)
        self.seen.origins = {}

    def tick(self) -> None:
        if self.closed:
            return
        state = self.read("defence_state", {})
        if "phase" not in state:
            return
        ended = state.get("phase") == ENDED
        if not (self.idle or ended):
            return
        feed = self.gathered(state)
        if feed.ended:
            self.sent(feed)
            self.stop()
        elif feed.news:
            self.sent(feed)
