from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cr import errors
from cr.config import configured
from telemetry import elastic
from training.models import Action, Origin, Round

DENY = "deny"
LIMIT_REQ = "limit_req"
ORIGIN_MARKER = "log:"
WHOLE_LOG_PAGE = 5000
DENIED = re.compile(r"\baccess forbidden by rule, client: ([0-9A-Fa-f.:]+),")
LIMITED = re.compile(r'\blimiting requests, excess: [0-9.]+ by zone "([^"]+)", client: ([0-9A-Fa-f.:]+),')


@dataclass(frozen=True)
class OriginRequest:
    id: str
    at: datetime
    ip: str
    method: str
    host: str | None
    path: str

    @property
    def marker(self) -> str:
        return f"{ORIGIN_MARKER}{self.id}"


@dataclass(frozen=True)
class Refusal:
    at: datetime
    ip: str
    by: str
    zone: str = ""


def refusal_in(line: str, at: datetime) -> Refusal | None:
    denied = DENIED.search(line)
    if denied:
        return Refusal(at=at, ip=denied.group(1), by=DENY)
    limited = LIMITED.search(line)
    if limited:
        return Refusal(at=at, ip=limited.group(2), by=LIMIT_REQ, zone=limited.group(1))
    return None


def refusals(found: Round, cursor: Mapping[str, Any] | None) -> tuple[list[Refusal], dict]:
    cfg = configured().elastic
    events, moved = elastic.error_events(cfg.url, cfg.index_of(found.allocation.slot or 0), dict(cursor or {}))
    found_refusals = [refusal for event in events if event["at"] is not None
                      and (refusal := refusal_in(event["line"], event["at"])) is not None]
    return found_refusals, moved


def encoded(cursor: Mapping[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(dict(cursor), sort_keys=True).encode()).decode()


def decoded(token: str) -> dict:
    try:
        cursor = json.loads(base64.urlsafe_b64decode(token.encode()))
    except (binascii.Error, ValueError) as broken:
        raise errors.Invalid(code="invalid", path="after") from broken
    if not isinstance(cursor, dict):
        raise errors.Invalid(code="invalid", path="after")
    return cursor


def read_now() -> datetime:
    return datetime.now(timezone.utc)


def traffic(found: Round, after: str = "") -> dict:
    cfg = configured().elastic
    start = found.started or found.allocation.opened
    since = str(decoded(after).get("at") or start.isoformat()) if after else start.isoformat()
    events, moved = elastic.settled_access_events(cfg.url, cfg.index_of(found.allocation.slot or 0), since,
                                                  now=read_now())
    by_origin: dict[str, dict] = {}
    for event in events:
        if not event["source_ip"]:
            continue
        origin = by_origin.setdefault(event["source_ip"], {"ip": event["source_ip"], "requests": 0, "refused": 0,
                                                           "last_at": None})
        origin["requests"] += 1
        origin["refused"] += int(event["refused"])
        if event["at"] and (origin["last_at"] is None or event["at"] > origin["last_at"]):
            origin["last_at"] = event["at"]
    return {"by_origin": sorted(by_origin.values(), key=lambda origin: origin["ip"]), "next": encoded({"at": moved})}


def request_line(request: str) -> tuple[str, str] | None:
    parts = request.split(" ")
    if len(parts) < 2 or not parts[0] or not parts[1].startswith("/"):
        return None
    return parts[0], parts[1]


def logged_rows(found: Round):
    cfg = configured().elastic
    index = cfg.index_of(found.allocation.slot or 0)
    cursor: dict = {"at": found.started.isoformat()}
    handed: set[str] = set()
    while True:
        events, cursor = elastic.access_events(cfg.url, index, cursor, WHOLE_LOG_PAGE)
        fresh = [event for event in events if event["id"] not in handed]
        if not fresh:
            return
        handed.update(event["id"] for event in fresh)
        yield from fresh


def origin_requests(found: Round) -> tuple[OriginRequest, ...]:
    if found.started is None:
        return ()
    ips = set(Origin.objects.filter(round=found).values_list("ip", flat=True))
    if not ips:
        return ()
    known = set(Action.objects.filter(round=found).values_list("marker", flat=True))
    made = []
    for row in logged_rows(found):
        at = row["at"]
        if at is not None and found.ended is not None and at > found.ended:
            break
        if at is None or at < found.started:
            continue
        if row["source_ip"] not in ips or (row["marker"] and row["marker"] in known):
            continue
        line = request_line(row["request"])
        if line is None:
            continue
        made.append(OriginRequest(id=row["id"], at=at, ip=row["source_ip"], method=line[0], host=row.get("host"),
                                  path=line[1]))
    return tuple(made)
