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


def request_key(marker: str | None, src_ip: str | None, uri: str) -> tuple:
    return (marker,) if marker else (None, src_ip or None, uri)


def same_request(one: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    if request_key(one["marker"], one["src_ip"], one["uri"]) != request_key(other["marker"], other["src_ip"],
                                                                            other["uri"]):
        return False
    return bool(one["marker"]) or abs(one["timestamp"] - other["timestamp"]) <= SAME_REQUEST_WITHIN


def stored_blocked_near(found, requests: list[Mapping[str, Any]], from_modsecurity: bool) -> list[dict]:
    if not requests:
        return []
    markers = sorted({one["marker"] for one in requests if one["marker"]})
    unmarked = [one for one in requests if not one["marker"]]
    near = models.Q(marker__in=markers) if markers else models.Q(pk__in=[])
    if unmarked:
        times = [one["timestamp"] for one in unmarked]
        near |= models.Q(marker__isnull=True, src_ip__in=sorted({one["src_ip"] for one in unmarked if one["src_ip"]}),
                         uri__in=sorted({one["uri"] for one in unmarked}),
                         timestamp__range=(min(times) - SAME_REQUEST_WITHIN, max(times) + SAME_REQUEST_WITHIN))
    rows = Detection.objects.filter(near, round=found, engine=ENGINE_WAF, blocked=True)
    rows = rows.filter(raw__has_key=MODSECURITY_KEY) if from_modsecurity else rows.exclude(raw__has_key=MODSECURITY_KEY)
    return list(rows.values("pk", "marker", "src_ip", "uri", "timestamp"))


def matching_any(one: Mapping[str, Any], others: list[Mapping[str, Any]]) -> bool:
    return any(same_request(one, other) for other in others)


def without_nul(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(NUL, "")
    if isinstance(value, Mapping):
        return {without_nul(key): without_nul(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [without_nul(item) for item in value]
    return value


def as_request(detection: Mapping[str, Any]) -> dict[str, Any]:
    return {"marker": detection.get("marker") or None, "src_ip": detection.get("src_ip") or None,
            "uri": uri_of(detection), "timestamp": detection.get("timestamp") or timezone.now()}


def row_of(found, detection: Mapping[str, Any]) -> Detection:
    request = as_request(detection)
    return Detection(round=found, detection_id=str(detection["detection_id"]), engine=ENGINE_OF[detection["source"]],
                     rule=rule_of(detection), signature=str(detection.get("signature") or ""),
                     severity=detection.get("severity"), timestamp=request["timestamp"], src_ip=request["src_ip"],
                     marker=request["marker"], uri=request["uri"], blocked=blocked(detection),
                     raw=detection.get("raw") or {})


def not_yet_stored(found, detections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fresh = {str(one["detection_id"]): without_nul(one) for one in detections if one["source"] in ENGINE_OF}
    held = set(Detection.objects.filter(round=found, detection_id__in=list(fresh)).values_list("detection_id",
                                                                                              flat=True))
    return [one for detection_id, one in fresh.items() if detection_id not in held]


def refused_by_modsecurity(detection: Mapping[str, Any]) -> bool:
    return detection["source"] == "modsecurity" and blocked(detection)


def stored_all(found, detections: list[Mapping[str, Any]]) -> list[Detection]:
    fresh = not_yet_stored(found, detections)
    refusals = [as_request(one) for one in fresh if refused_by_modsecurity(one)]
    access = [one for one in fresh if one["source"] == "nginx"]
    refused = refusals + stored_blocked_near(found, [as_request(one) for one in access], from_modsecurity=True)
    kept = [one for one in fresh if one["source"] != "nginx" or not matching_any(as_request(one), refused)]
    rows = Detection.objects.bulk_create([row_of(found, one) for one in kept]) if kept else []
    drop_access_refusals_of(found, refusals)
    log.append_all(found.pk, "alert.seen", [{"alert": row.pk, "engine": row.engine, "signature": row.signature}
                                            for row in rows], player_side=DEFENCE)
    return rows


def drop_access_refusals_of(found, refusals: list[Mapping[str, Any]]) -> None:
    doubles = [row["pk"] for row in stored_blocked_near(found, refusals, from_modsecurity=False)
               if matching_any(row, refusals)]
    if doubles:
        Detection.objects.filter(pk__in=doubles).delete()


def forget(round_ids: list[int]) -> int:
    deleted, _ = Detection.objects.filter(round_id__in=list(round_ids)).delete()
    return deleted


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
        made += stored_all(found, elastic.normalize_all(documents, joins))
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
