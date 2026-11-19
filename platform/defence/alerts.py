from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from cr.config import ElasticConfig
from defence.models import AlertCursor, Detection
from domain.types import ENGINE_IDS, ENGINE_WAF
from events import log
from ingest import elastic

ENGINE_OF = {"suricata": ENGINE_IDS, "modsecurity": ENGINE_WAF, "nginx": ENGINE_WAF}
MOST_PAGES = 5
DEFENCE = "defence"


def rule_of(detection: Mapping[str, Any]) -> str:
    raw = detection.get("raw") or {}
    if detection["source"] == "suricata":
        return str((raw.get("alert") or {}).get("signature_id") or "")
    if detection["source"] == "modsecurity":
        return str((raw.get("details") or {}).get("ruleId") or "")
    return str(detection.get("signature") or "").partition(" ")[0]


def uri_of(detection: Mapping[str, Any]) -> str:
    raw = detection.get("raw") or {}
    if detection["source"] == "suricata":
        return str((raw.get("http") or {}).get("url") or "")
    if detection["source"] == "modsecurity":
        return str((raw.get("request") or {}).get("uri") or "")
    request = str(raw.get("request") or "").split(" ")
    return request[1] if len(request) > 1 else ""


def blocked(detection: Mapping[str, Any]) -> bool:
    if detection["source"] == "nginx":
        return True
    return str(((detection.get("raw") or {}).get("alert") or {}).get("action") or "") == "blocked"


def stored(found, detection: Mapping[str, Any]) -> Detection | None:
    engine = ENGINE_OF.get(detection["source"])
    if engine is None:
        return None
    row, created = Detection.objects.get_or_create(round=found, detection_id=str(detection["detection_id"]), defaults={
        "engine": engine, "rule": rule_of(detection), "signature": str(detection.get("signature") or ""),
        "severity": detection.get("severity"), "timestamp": detection.get("timestamp") or timezone.now(),
        "src_ip": detection.get("src_ip") or None, "marker": detection.get("marker"), "uri": uri_of(detection),
        "blocked": blocked(detection), "raw": detection.get("raw") or {}})
    if not created:
        return None
    log.append(found.pk, "alert.seen", {"alert": row.pk, "engine": row.engine, "signature": row.signature},
               seat_side=DEFENCE)
    return row


def cursor_of(found) -> AlertCursor:
    held, _ = AlertCursor.objects.get_or_create(lease=found.lease,
                                                defaults={"cursor": {"at": found.lease.opened.isoformat()}})
    return held


def ingest(found, config: ElasticConfig) -> list[Detection]:
    held = cursor_of(found)
    index = config.index_of(found.lease.slot or 0)
    made: list[Detection] = []
    for _ in range(MOST_PAGES):
        documents, moved = elastic.fetch_after(config.url, index, held.cursor)
        made += [row for detection in elastic.normalize_all(documents) if (row := stored(found, detection))]
        held.cursor = moved
        held.save(update_fields=["cursor"])
        if len(documents) < elastic.PAGE:
            break
    return made
