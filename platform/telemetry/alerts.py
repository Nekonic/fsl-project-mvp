from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from cr.config import ElasticConfig, configured
from domain.types import ENGINE_IDS, ENGINE_WAF, DetectionRecord
from telemetry import elastic
from telemetry import events as log
from telemetry.models import AlertCursor, Detection
from training.models import Round

ENGINE_OF = {"suricata": ENGINE_IDS, "modsecurity": ENGINE_WAF, "nginx": ENGINE_WAF}
MOST_PAGES = 5
MOST_JOINS = 2000
ALERTS_PAGE = 200
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
               player_side=DEFENCE)
    return row


def cursor_of(found) -> AlertCursor:
    held, _ = AlertCursor.objects.get_or_create(allocation=found.allocation,
                                                defaults={"cursor": {"at": found.allocation.opened.isoformat()}})
    return held


def ingest(found, config: ElasticConfig) -> list[Detection]:
    held = cursor_of(found)
    index = config.index_of(found.allocation.slot or 0)
    joins = dict(held.cursor.get("joins") or {})
    made: list[Detection] = []
    for _ in range(MOST_PAGES):
        documents, moved = elastic.fetch_after(config.url, index, held.cursor)
        page = elastic.transaction_joins(documents)
        joins = elastic.joined_with(joins, page)
        made += [row for detection in elastic.normalize_all(documents, joins) if (row := stored(found, detection))]
        joined_later(found, page)
        held.cursor = {**moved, "joins": dict(list(joins.items())[-MOST_JOINS:])}
        held.save(update_fields=["cursor"])
        if len(documents) < elastic.PAGE:
            break
    return made


def joined_later(found, joins: Mapping[str, Mapping[str, Any]]) -> None:
    for join in joins.values():
        rows = Detection.objects.filter(round=found, engine=ENGINE_IDS, raw__flow_id=join["flow_id"],
                                        raw__tx_id=join["tx_id"])
        if join.get("marker"):
            rows.filter(marker__isnull=True).update(marker=join["marker"])
        if join.get("xff"):
            rows.update(src_ip=join["xff"])


def alerts(found: Round, after: int = 0, engine: str = "", rule: str = "", src: str = "") -> tuple[list, int]:
    rows = Detection.objects.filter(round=found, id__gt=after)
    if engine:
        rows = rows.filter(engine=engine)
    if rule:
        rows = rows.filter(rule=rule)
    if src:
        rows = rows.filter(src_ip=src)
    page = list(rows.order_by("id")[:ALERTS_PAGE])
    return page, page[-1].pk if page else after


def detections(found: Round) -> tuple[DetectionRecord, ...]:
    return tuple(DetectionRecord(detection_id=row.detection_id, timestamp=row.timestamp, src_ip=row.src_ip,
                                 marker=row.marker, engine=row.engine, rule=row.rule, signature=row.signature,
                                 uri=row.uri, blocked=row.blocked)
                 for row in Detection.objects.filter(round=found).order_by("timestamp", "id"))


def ingest_alerts(found: Round) -> list[Detection]:
    return ingest(found, configured().elastic)
