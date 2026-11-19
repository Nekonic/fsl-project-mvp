from __future__ import annotations

from dataclasses import dataclass

from events.kinds import KINDS, SIDES, Viewer, malformed, shown_body, visible_kinds
from events.models import Event

PAGE = 200


@dataclass(frozen=True)
class Page:
    events: list[dict]
    next: int


def append(round_id: int, kind: str, body: dict | None = None, seat_side: str | None = None) -> Event:
    if kind not in KINDS:
        raise LookupError(f"no event kind {kind!r}")
    if seat_side is not None and seat_side not in SIDES:
        raise TypeError(f"seat_side {seat_side!r} is not a side")
    given = dict(body or {})
    problems = malformed(kind, given)
    if problems:
        raise TypeError(f"{kind} body: {', '.join(problems)}")
    return Event.objects.create(round_id=round_id, kind=kind, seat_side=seat_side, body=given)


def forget(round_ids: list[int]) -> int:
    deleted, _ = Event.objects.filter(round_id__in=list(round_ids)).delete()
    return deleted


def shown(event: Event, viewer: Viewer) -> dict:
    return {"id": event.id, "kind": event.kind, "at": event.at, "seat_side": event.seat_side,
            "body": shown_body(event.kind, event.body, viewer)}


def after(round_id: int, cursor: int, viewer: Viewer, limit: int = PAGE) -> Page:
    found = list(Event.objects.filter(round_id=round_id, id__gt=cursor, kind__in=visible_kinds(viewer))
                 .order_by("id")[:limit])
    return Page(events=[shown(event, viewer) for event in found], next=found[-1].id if found else cursor)
