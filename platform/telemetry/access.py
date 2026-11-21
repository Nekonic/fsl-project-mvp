from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cr import errors
from cr.config import configured
from telemetry import elastic
from training.models import Round

DENY = "deny"
LIMIT_REQ = "limit_req"
DENIED = re.compile(r"\baccess forbidden by rule, client: ([0-9A-Fa-f.:]+),")
LIMITED = re.compile(r'\blimiting requests, excess: [0-9.]+ by zone "([^"]+)", client: ([0-9A-Fa-f.:]+),')


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


def traffic(found: Round, after: str = "") -> dict:
    cfg = configured().elastic
    start = found.started or found.allocation.opened
    cursor = decoded(after) if after else {"at": start.isoformat()}
    events, moved = elastic.access_events(cfg.url, cfg.index_of(found.allocation.slot or 0), cursor)
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
    return {"by_origin": sorted(by_origin.values(), key=lambda origin: origin["ip"]), "next": encoded(moved)}
