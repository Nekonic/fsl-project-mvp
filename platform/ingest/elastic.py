"""Elasticsearch queries and alert normalisation. The only file that knows ES."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import requests

MARKER_HEADER = "X-FSL-Case"
_MARKER_KEY = MARKER_HEADER.lower()


class ElasticUnavailable(RuntimeError):
    """Cannot reach ES, or the index is absent. Distinct from "nothing detected"."""


def fetch(
    url: str,
    index: str,
    start: datetime,
    end: datetime,
    size: int = 5000,
    timeout: float = 10.0,
) -> list[tuple[str, dict[str, Any]]]:
    """Return documents in the interval as (_id, _source) pairs."""
    query = {
        "size": size,
        "sort": [{"@timestamp": "asc"}],
        "query": {
            "range": {
                "@timestamp": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                }
            }
        },
    }

    try:
        response = requests.post(
            f"{url.rstrip('/')}/{index}/_search",
            json=query,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ElasticUnavailable(f"could not reach Elasticsearch: {exc}") from exc

    if response.status_code == 404:
        raise ElasticUnavailable(
            f"index {index!r} does not exist. Filebeat may not have shipped "
            f"anything yet."
        )
    if not response.ok:
        raise ElasticUnavailable(
            f"Elasticsearch returned {response.status_code}: {response.text[:500]}"
        )

    hits = response.json().get("hits", {}).get("hits", [])
    return [(hit["_id"], hit.get("_source", {})) for hit in hits]


def normalize_all(
    documents: Sequence[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Turn a batch of documents into alerts, joining markers per transaction.

    A Suricata alert carries no request headers; they live on the http event of
    the same transaction, so the batch must be walked twice. The join key is
    (flow_id, tx_id): under keep-alive many requests share one flow, and joining
    on flow_id alone pins that flow's first marker onto every alert in it - a
    plausible-looking, quietly false score. Both verified against the stack.
    """
    markers = _transaction_markers(documents)

    detections: list[dict[str, Any]] = []
    for doc_id, doc in documents:
        key = _transaction_key(doc)
        for detection in normalize(doc_id, doc):
            if detection["marker"] is None and key is not None:
                detection["marker"] = markers.get(key)
            detections.append(detection)
    return detections


def _transaction_markers(
    documents: Sequence[tuple[str, dict[str, Any]]],
) -> dict[tuple[Any, Any], str]:
    """(flow_id, tx_id) -> marker, collected from the http events that carry it."""
    markers: dict[tuple[Any, Any], str] = {}
    for _, doc in documents:
        key = _transaction_key(doc)
        if key is None or key in markers:
            continue
        marker = _suricata_marker(doc.get("http") or {})
        if marker:
            markers[key] = marker
    return markers


def _transaction_key(doc: dict[str, Any]) -> tuple[Any, Any] | None:
    flow_id = doc.get("flow_id")
    if flow_id is None:
        return None
    return (flow_id, doc.get("tx_id"))


def normalize(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one document into zero or more alerts.

    Documents that are not alerts (Suricata http/flow events, ModSecurity
    transactions that matched no rule) yield an empty list.
    """
    source = doc.get("fsl_source")
    if source == "suricata":
        return _normalize_suricata(doc_id, doc)
    if source == "modsecurity":
        return _normalize_modsecurity(doc_id, doc)
    return []


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
            "marker": _suricata_marker(doc.get("http") or {}),
            "raw": doc,
        }
    ]


def _normalize_modsecurity(doc_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    transaction = doc.get("transaction") or {}
    messages = transaction.get("messages") or []
    if not messages:
        return []

    headers = ((transaction.get("request") or {}).get("headers")) or {}
    marker = _header_lookup(headers)
    timestamp = _parse_time(transaction.get("time_stamp")) or _parse_time(
        doc.get("@timestamp")
    )
    src_ip = transaction.get("client_ip")

    detections = []
    for position, message in enumerate(messages):
        details = message.get("details") or {}
        signature = message.get("message") or ""
        if not signature:
            rule_id = details.get("ruleId")
            signature = f"ruleId {rule_id}" if rule_id else "unnamed ModSecurity rule"

        detections.append(
            {
                "detection_id": f"{doc_id}:{position}",
                "source": "modsecurity",
                "signature": signature,
                "severity": _as_int(details.get("severity")),
                "timestamp": timestamp,
                "src_ip": src_ip,
                "marker": marker,
                "raw": message,
            }
        )
    return detections


# Each engine logs the marker in exactly one place. Matching is case-insensitive
# because HTTP header names are, but nothing else is guessed at: if the marker
# is ever missed, correlate() warns and the acceptance tests fail on it, so the
# failure is loud rather than a session of silent false negatives.


def _suricata_marker(http: dict[str, Any]) -> str | None:
    """Suricata logs request headers as a list, under dump-all-headers."""
    for header in http.get("request_headers") or []:
        if str(header.get("name", "")).lower() == _MARKER_KEY:
            return header.get("value")
    return None


def _header_lookup(headers: dict[str, Any]) -> str | None:
    """ModSecurity logs them as a dict, keyed as the client sent them."""
    return next(
        (v for k, v in headers.items() if str(k).lower() == _MARKER_KEY and v), None
    )


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    # Suricata writes +0000, Elasticsearch writes Z. Accept both.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) >= 5 and text[-5] in "+-" and ":" not in text[-5:]:
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    # ModSecurity audit logs use ctime, not ISO: "Fri Sep 18 15:25:02 2026".
    # There is no timezone, so read it as UTC - the container runs in UTC.
    for fmt in ("%a %b %d %H:%M:%S %Y", "%a %b %d %H:%M:%S.%f %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
