from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
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
LATE_SECONDS = 30.0
SETTLE_SECONDS = 15.0
PIPELINE_TRIES = 30
PIPELINE_PAUSE = 2.0


class ElasticUnavailable(Unavailable):
    code = "elastic_unavailable"

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
    joined: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    joins = joined_with(joined or {}, transaction_joins(documents))

    detections: list[dict[str, Any]] = []
    for doc_id, doc in documents:
        join = joins.get(_transaction_key(doc) or "") or {}
        for detection in normalize(doc_id, doc):
            if detection["marker"] is None and join.get("marker"):
                detection["marker"] = join["marker"]
            if detection["source"] == "suricata" and join.get("xff"):
                detection["src_ip"] = join["xff"]
            detections.append(detection)
    return detections


def transaction_joins(documents: Sequence[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    joins: dict[str, dict[str, Any]] = {}
    for _, doc in documents:
        key = _transaction_key(doc)
        if key is None:
            continue
        marker, forwarded = suricata_marker(doc.get("http") or {}), doc.get("xff")
        if not marker and not forwarded:
            continue
        held = joins.setdefault(key, {"flow_id": doc["flow_id"], "tx_id": doc.get("tx_id")})
        if marker and not held.get("marker"):
            held["marker"] = marker
        if forwarded:
            held["xff"] = forwarded
    return joins


def joined_with(earlier: Mapping[str, Mapping[str, Any]],
                later: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    joins = {key: dict(join) for key, join in earlier.items()}
    for key, join in later.items():
        held = joins.setdefault(key, {})
        held.update({name: value for name, value in join.items() if name != "marker" or not held.get("marker")})
    return joins


def _transaction_key(doc: dict[str, Any]) -> str | None:
    flow_id = doc.get("flow_id")
    if flow_id is None:
        return None
    return f"{flow_id}/{doc.get('tx_id')}"


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
        "host": doc.get("vhost") or None,
    }


def _normalize_access(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    record = access_record(doc_id, doc)
    if not record["refused"]:
        return []
    return [{"detection_id": doc_id, "source": "nginx", "signature": f"{record['status']} {record['request']}",
             "severity": None, "timestamp": record["at"], "src_ip": record["source_ip"],
             "marker": record["marker"], "blocked": True, "raw": doc}]


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
            "blocked": str(alert.get("action") or "") == "blocked",
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
    refused = _as_int((transaction.get("response") or {}).get("http_code")) in REFUSED_STATUSES

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
                "blocked": refused,
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


def _stamp(value: Any) -> datetime | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _seen_of(cursor: Mapping[str, Any]) -> dict[str, str]:
    seen = cursor.get("seen") or {}
    if isinstance(seen, Mapping):
        return {str(doc_id): str(at) for doc_id, at in seen.items()}
    return {str(doc_id): str(cursor.get("at") or "") for doc_id in seen}


def _lower_bound(at: Any) -> str | None:
    moment = _stamp(at)
    if moment is None:
        return str(at) if at else None
    return _iso(moment - timedelta(seconds=LATE_SECONDS))


def _range(field_name: str, bounds: dict[str, str]) -> dict[str, Any]:
    return {"range": {field_name: bounds}}


def _sorted_at(hit: dict) -> Any:
    return (hit.get("sort") or [None])[0] or hit.get("_source", {}).get("@timestamp")


EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def _later(one: Any, other: Any) -> Any:
    if not one:
        return other
    return one if (_stamp(one) or EARLIEST) > (_stamp(other) or EARLIEST) else other


def _kept_seen(seen: dict[str, str], last: Any) -> dict[str, str]:
    newest = _stamp(last)
    if newest is None:
        return seen
    oldest = newest - timedelta(seconds=LATE_SECONDS)
    return {doc_id: at for doc_id, at in seen.items() if (_stamp(at) or newest) >= oldest}


def _documents(hits: list[dict]) -> list[tuple[str, dict[str, Any]]]:
    return [(hit["_id"], hit.get("_source", {})) for hit in hits]


def _search(url: str, index: str, filters: list[dict], size: int, must_not: list[dict] | None = None) -> list[dict]:
    body = {
        "size": size,
        "track_total_hits": False,
        "_source": {"excludes": ["message"]},
        "sort": [{"@timestamp": {"order": "asc", "format": "strict_date_optional_time_nanos"}}],
        "query": {"bool": {"filter": filters, "must_not": must_not or []}},
    }
    return _posted(url, index, "_search?allow_partial_search_results=false", body).json().get(
        "hits", {}).get("hits", [])


def fetch_after(url: str, index: str, cursor: dict | None = None, size: int = PAGE,
                module: str | None = None) -> tuple[list[tuple[str, dict[str, Any]]], dict]:
    previous = dict(cursor or {})
    lowest = _lower_bound(previous.get("at"))
    filters = [_range("@timestamp", {"gte": lowest})] if lowest else []
    if module:
        filters.append({"term": {"event.module": module}})
    hits = _search(url, index, filters, size, [{"ids": {"values": sorted(_seen_of(previous))}}])
    if not hits:
        return [], previous
    latest = _later(previous.get("at"), _sorted_at(hits[-1]))
    seen = {**_seen_of(previous), **{hit["_id"]: str(_sorted_at(hit)) for hit in hits}}
    return _documents(hits), {"at": latest, "seen": _kept_seen(seen, latest)}


def settled_after(url: str, index: str, since: str, until: datetime, size: int = PAGE,
                  module: str | None = None) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    filters: list[dict] = [_range("@timestamp", {"gte": since, "lt": _iso(until)})]
    if module:
        filters.append({"term": {"event.module": module}})
    hits = _search(url, index, filters, size)
    if len(hits) < size:
        return _documents(hits), _later(since, _iso(until))
    last = _sorted_at(hits[-1])
    whole = [hit for hit in hits if _sorted_at(hit) != last]
    if whole:
        return _documents(whole), str(last)
    return _documents(hits), _iso((_stamp(last) or until) + timedelta(microseconds=1))


def access_events(url: str, index: str, cursor: dict | None = None,
                  size: int = PAGE) -> tuple[list[dict[str, Any]], dict]:
    documents, moved = fetch_after(url, index, cursor, size, module=ACCESS_MODULE)
    return [access_record(doc_id, doc) for doc_id, doc in documents
            if (doc.get("event") or {}).get("module") == ACCESS_MODULE], moved


def settled_access_events(url: str, index: str, since: str, now: datetime | None = None,
                           size: int = PAGE) -> tuple[list[dict[str, Any]], str]:
    until = (now or datetime.now(timezone.utc)) - timedelta(seconds=SETTLE_SECONDS)
    documents, moved = settled_after(url, index, since, until, size, module=ACCESS_MODULE)
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
