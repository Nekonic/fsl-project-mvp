from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from django.db import models
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
NUL = "\x00"
SAME_REQUEST_WITHIN = timedelta(seconds=2)
MODSECURITY_KEY = "details"


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
    return bool(detection.get("blocked"))


def same_request(found, marker: str | None, src_ip: str | None, uri: str, at) -> models.QuerySet:
    rows = Detection.objects.filter(round=found, engine=ENGINE_WAF, blocked=True)
    if marker:
        return rows.filter(marker=marker)
    return rows.filter(marker__isnull=True, src_ip=src_ip or None, uri=uri,
                       timestamp__range=(at - SAME_REQUEST_WITHIN, at + SAME_REQUEST_WITHIN))


def refused_by_modsecurity(found, detection: Mapping[str, Any]) -> bool:
    return same_request(found, detection.get("marker"), detection.get("src_ip"), uri_of(detection),
                        detection.get("timestamp") or timezone.now()).filter(raw__has_key=MODSECURITY_KEY).exists()


def drop_access_refusals_of(row: Detection) -> None:
    same_request(row.round, row.marker, row.src_ip, row.uri, row.timestamp).exclude(
        raw__has_key=MODSECURITY_KEY).delete()


def without_nul(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(NUL, "")
    if isinstance(value, Mapping):
        return {without_nul(key): without_nul(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [without_nul(item) for item in value]
    return value


def stored(found, detection: Mapping[str, Any]) -> Detection | None:
    detection = without_nul(detection)
    engine = ENGINE_OF.get(detection["source"])
    if engine is None:
        return None
    if detection["source"] == "nginx" and refused_by_modsecurity(found, detection):
        return None
    row, created = Detection.objects.get_or_create(round=found, detection_id=str(detection["detection_id"]), defaults={
        "engine": engine, "rule": rule_of(detection), "signature": str(detection.get("signature") or ""),
        "severity": detection.get("severity"), "timestamp": detection.get("timestamp") or timezone.now(),
        "src_ip": detection.get("src_ip") or None, "marker": detection.get("marker"), "uri": uri_of(detection),
        "blocked": blocked(detection), "raw": detection.get("raw") or {}})
    if not created:
        return None
    if detection["source"] == "modsecurity" and row.blocked:
        drop_access_refusals_of(row)
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
    wanted = {(join["flow_id"], join["tx_id"]): join for join in joins.values()}
    if not wanted:
        return
    flows = sorted({flow for flow, _ in wanted}, key=str)
    rows = Detection.objects.filter(round=found, engine=ENGINE_IDS, raw__flow_id__in=flows)
    for pk, raw, marker in rows.values_list("pk", "raw", "marker"):
        join = wanted.get(((raw or {}).get("flow_id"), (raw or {}).get("tx_id")))
        if join is None:
            continue
        changed = {**({"marker": join["marker"]} if join.get("marker") and marker is None else {}),
                   **({"src_ip": join["xff"]} if join.get("xff") else {})}
        if changed:
            Detection.objects.filter(pk=pk).update(**changed)


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
