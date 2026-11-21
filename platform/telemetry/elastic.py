from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from cr.config import ElasticConfig
from cr.errors import Unavailable

MARKER_HEADER = "X-Request-ID"
_MARKER_KEY = MARKER_HEADER.lower()

FETCH_TIMEOUT = 10.0

ACCESS_MODULE = "nginx_access"
ERROR_MODULE = "nginx_error"
REFUSED_STATUSES = (400, 403)
PAGE = 1000
PIPELINE_TRIES = 30
PIPELINE_PAUSE = 2.0


class ElasticUnavailable(Unavailable):
    code = "elastic_unavailable"

def fetch(
    url: str,
    index: str,
    start: datetime,
    end: datetime,
    size: int = 5000,
    newest_first: bool = False,
) -> tuple[list[tuple[str, dict[str, Any]]], tuple[int, int] | None]:
    query = {
        "size": size,
        "track_total_hits": True,
        "_source": {"excludes": ["message"]},
        "sort": [{"@timestamp": "desc" if newest_first else "asc"}],
        "query": {
            "range": {
                "@timestamp": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                }
            }
        },
    }

    response = _posted(url, index, "_search?allow_partial_search_results=false", query)

    found = response.json().get("hits", {})
    hits = found.get("hits", [])
    total = (found.get("total") or {}).get("value", len(hits))
    documents = [(hit["_id"], hit.get("_source", {})) for hit in hits]
    return documents, (len(hits), total) if total > len(hits) else None

def forget_before(url: str, index: str, before: datetime) -> None:
    _posted(url, index, "_delete_by_query?conflicts=proceed&wait_for_completion=false",
            {"query": {"range": {"@timestamp": {"lt": before.isoformat()}}}})

def _posted(url: str, index: str, call: str, body: dict[str, Any]) -> requests.Response:
    try:
        response = requests.post(f"{url.rstrip('/')}/{index}/{call}", json=body, timeout=FETCH_TIMEOUT)
    except requests.RequestException as exc:
        raise ElasticUnavailable(f"could not reach Elasticsearch: {exc}") from exc
    if response.status_code == 404:
        raise ElasticUnavailable(f"index {index!r} does not exist. Filebeat may not have shipped anything yet.")
    if not response.ok:
        raise ElasticUnavailable(f"Elasticsearch returned {response.status_code}: {response.text[:500]}")
    return response

def normalize_all(
    documents: Sequence[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    markers = _transaction_markers(documents)
    forwarded = {_transaction_key(doc): doc["xff"] for _, doc in documents if doc.get("xff") and _transaction_key(doc)}

    detections: list[dict[str, Any]] = []
    for doc_id, doc in documents:
        key = _transaction_key(doc)
        for detection in normalize(doc_id, doc):
            if detection["marker"] is None and key is not None:
                detection["marker"] = markers.get(key)
            if detection["source"] == "suricata" and key in forwarded:
                detection["src_ip"] = forwarded[key]
            detections.append(detection)
    return detections

def _transaction_markers(
    documents: Sequence[tuple[str, dict[str, Any]]],
) -> dict[tuple[Any, Any], str]:
    markers: dict[tuple[Any, Any], str] = {}
    for _, doc in documents:
        key = _transaction_key(doc)
        if key is None or key in markers:
            continue
        marker = suricata_marker(doc.get("http") or {})
        if marker:
            markers[key] = marker
    return markers

def _transaction_key(doc: dict[str, Any]) -> tuple[Any, Any] | None:
    flow_id = doc.get("flow_id")
    if flow_id is None:
        return None
    return (flow_id, doc.get("tx_id"))

def normalize(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    source = (doc.get("event") or {}).get("module")
    if source == "suricata":
        return _normalize_suricata(doc_id, doc)
    if source == "modsecurity":
        return _normalize_modsecurity(doc_id, doc)
    if source == ACCESS_MODULE:
        return _normalize_access(doc_id, doc)
    return []

def access_record(doc_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    status = _as_int(doc.get("status") or (doc.get("http") or {}).get("status")) or 0
    return {
        "id": doc_id,
        "at": _parse_time(doc.get("time")) or _parse_time(doc.get("@timestamp")),
        "source_ip": doc.get("client_ip") or doc.get("remote_addr"),
        "status": status,
        "refused": status in REFUSED_STATUSES,
        "marker": doc.get("request_id") or None,
        "request": doc.get("request", ""),
    }


def _normalize_access(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    record = access_record(doc_id, doc)
    if not record["refused"]:
        return []
    return [{"detection_id": doc_id, "source": "nginx", "signature": f"{record['status']} {record['request']}",
             "severity": None, "timestamp": record["at"], "src_ip": record["source_ip"],
             "marker": record["marker"], "raw": doc}]


def _normalize_suricata(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    if doc.get("event_type") != "alert":
        return []

    alert = doc.get("alert") or {}
    return [
        {
            "detection_id": doc_id,
            "source": "suricata",
            "signature": alert.get("signature", ""),
            "severity": alert.get("severity"),
            "timestamp": _parse_time(doc.get("timestamp")),
            "src_ip": doc.get("src_ip"),
            "marker": suricata_marker(doc.get("http") or {}),
            "raw": doc,
        }
    ]

def _normalize_modsecurity(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    transaction = doc.get("transaction") or {}
    messages = transaction.get("messages") or []
    if not messages:
        return []

    request = transaction.get("request") or {}
    marker = _header_lookup(request.get("headers") or {})
    timestamp = _parse_time(transaction.get("time_stamp")) or _parse_time(doc.get("@timestamp"))
    src_ip = transaction.get("client_ip")

    detections = []
    for position, message in enumerate(messages):
        details = message.get("details") or {}
        signature = message.get("message") or f"ruleId {details.get('ruleId')}"

        detections.append(
            {
                "detection_id": f"{doc_id}:{position}",
                "source": "modsecurity",
                "signature": signature,
                "severity": _as_int(details.get("severity")),
                "timestamp": timestamp,
                "src_ip": src_ip,
                "marker": marker,
                "raw": dict(message, src_geo=doc.get("src_geo") or {}, request=request,
                            host_ip=transaction.get("host_ip"), host_port=transaction.get("host_port")),
            }
        )
    return detections


def suricata_marker(http: dict[str, Any]) -> str | None:
    for header in http.get("request_headers") or []:
        if str(header.get("name", "")).lower() == _MARKER_KEY:
            return header.get("value")
    return None

def _header_lookup(headers: dict[str, Any]) -> str | None:
    return next(
        (v for k, v in headers.items() if str(k).lower() == _MARKER_KEY and v), None
    )

def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _after_query(cursor: dict | None, module: str | None, size: int) -> dict[str, Any]:
    cursor = cursor or {}
    filters: list[dict] = []
    if cursor.get("at"):
        filters.append({"range": {"@timestamp": {"gte": cursor["at"]}}})
    if module:
        filters.append({"term": {"event.module": module}})
    return {
        "size": size,
        "track_total_hits": False,
        "_source": {"excludes": ["message"]},
        "sort": [{"@timestamp": {"order": "asc", "format": "strict_date_optional_time_nanos"}}],
        "query": {"bool": {"filter": filters, "must_not": [{"ids": {"values": list(cursor.get("seen") or ())}}]}},
    }


def _sorted_at(hit: dict) -> Any:
    return (hit.get("sort") or [None])[0] or hit.get("_source", {}).get("@timestamp")


def fetch_after(url: str, index: str, cursor: dict | None = None, size: int = PAGE,
                module: str | None = None) -> tuple[list[tuple[str, dict[str, Any]]], dict]:
    previous = dict(cursor or {})
    response = _posted(url, index, "_search?allow_partial_search_results=false", _after_query(previous, module, size))
    hits = response.json().get("hits", {}).get("hits", [])
    documents = [(hit["_id"], hit.get("_source", {})) for hit in hits]
    if not hits:
        return documents, previous
    last = _sorted_at(hits[-1])
    seen = [hit["_id"] for hit in hits if _sorted_at(hit) == last]
    if last == previous.get("at"):
        seen = list(previous.get("seen") or ()) + seen
    return documents, {"at": last, "seen": seen}


def access_events(url: str, index: str, cursor: dict | None = None,
                  size: int = PAGE) -> tuple[list[dict[str, Any]], dict]:
    documents, moved = fetch_after(url, index, cursor, size, module=ACCESS_MODULE)
    return [access_record(doc_id, doc) for doc_id, doc in documents
            if (doc.get("event") or {}).get("module") == ACCESS_MODULE], moved


def error_events(url: str, index: str, cursor: dict | None = None,
                 size: int = PAGE) -> tuple[list[dict[str, Any]], dict]:
    documents, moved = fetch_after(url, index, cursor, size, module=ERROR_MODULE)
    return [{"id": doc_id, "at": _parse_time(doc.get("@timestamp")),
             "line": str((doc.get("error") or {}).get("message") or "")}
            for doc_id, doc in documents if (doc.get("event") or {}).get("module") == ERROR_MODULE], moved


def pipeline_endpoint(config: ElasticConfig) -> str:
    return f"{config.url.rstrip('/')}/_ingest/pipeline/{config.pipeline}"


def register_pipeline(config: ElasticConfig, tries: int = PIPELINE_TRIES,
                      pause: Callable[[float], None] = time.sleep) -> bool:
    body = Path(config.pipeline_file).read_bytes()
    for _ in range(tries):
        try:
            answer = requests.put(pipeline_endpoint(config), data=body, timeout=FETCH_TIMEOUT,
                                  headers={"Content-Type": "application/json"})
            if answer.status_code < 300:
                return True
        except requests.RequestException:
            pass
        pause(PIPELINE_PAUSE)
    return False
