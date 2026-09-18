"""Elasticsearch 조회와 경보 정규화. 스택에서 ES 를 아는 유일한 파일."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import requests

MARKER_HEADER = "X-FSL-Case"

# Suricata 가 eve-log 의 http custom 으로 내보내는 헤더 키 표기.
# 버전에 따라 하이픈이 밑줄로 바뀌거나 원래 표기가 유지된다.
_MARKER_KEYS = ("x_fsl_case", "X-FSL-Case", "x-fsl-case", "X_FSL_CASE")


class ElasticUnavailable(RuntimeError):
    """ES 에 닿지 못했거나 인덱스가 아직 없다. 탐지 실패와 구분해야 한다."""


def fetch(
    url: str,
    index: str,
    start: datetime,
    end: datetime,
    size: int = 5000,
    timeout: float = 10.0,
) -> list[tuple[str, dict[str, Any]]]:
    """구간에 걸친 문서를 (_id, _source) 목록으로 가져온다."""
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
        raise ElasticUnavailable(f"Elasticsearch 에 닿지 못했다: {exc}") from exc

    if response.status_code == 404:
        raise ElasticUnavailable(
            f"인덱스 {index!r} 가 없다. Filebeat 이 아직 아무것도 보내지 않았을 수 있다."
        )
    if not response.ok:
        raise ElasticUnavailable(
            f"Elasticsearch 가 {response.status_code} 를 반환했다: {response.text[:500]}"
        )

    hits = response.json().get("hits", {}).get("hits", [])
    return [(hit["_id"], hit.get("_source", {})) for hit in hits]


def normalize_all(
    documents: Sequence[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """문서 묶음을 경보 목록으로 바꾼다. 마커는 트랜잭션 단위로 조인한다.

    Suricata 의 alert 이벤트는 HTTP 요청 헤더를 담지 않는다 — 헤더는 같은
    트랜잭션의 http 이벤트에만 실린다. 그래서 마커는 문서 하나만 보고는
    알 수 없고, 두 번 훑어야 한다.

    조인 키는 `flow_id` 하나가 아니라 `(flow_id, tx_id)` 다. HTTP keep-alive
    에서는 TCP 흐름 하나 위로 요청 수십 개가 흐르므로, flow_id 만으로 조인하면
    흐름의 첫 마커가 그 흐름의 모든 경보에 붙어 전부 엉뚱한 케이스로 귀속된다.
    점수는 그럴듯해 보이면서 조용히 거짓이 된다. 실제 스택에서 확인한 사실이다.
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
    """(flow_id, tx_id) -> 마커. http 이벤트가 싣고 다니는 것을 모은다."""
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
    """ES 문서 하나를 0개 이상의 경보로 바꾼다.

    경보가 아닌 문서(Suricata 의 http/flow 이벤트, 룰에 걸리지 않은
    ModSecurity 트랜잭션)는 빈 목록이 된다.
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


def _suricata_marker(http: dict[str, Any]) -> str | None:
    direct = _header_lookup(http)
    if direct:
        return direct

    for header in http.get("request_headers") or []:
        if str(header.get("name", "")).lower() == MARKER_HEADER.lower():
            return header.get("value")
    return None


def _header_lookup(headers: dict[str, Any]) -> str | None:
    for key in _MARKER_KEYS:
        value = headers.get(key)
        if value:
            return value
    # 대소문자만 다른 경우까지 훑는다.
    wanted = MARKER_HEADER.lower().replace("-", "_")
    for key, value in headers.items():
        if str(key).lower().replace("-", "_") == wanted and value:
            return value
    return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    # Suricata 는 +0000, ES 는 Z 를 쓴다. 둘 다 받는다.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) >= 5 and text[-5] in "+-" and ":" not in text[-5:]:
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    # ModSecurity 감사 로그는 ISO 가 아니라 ctime 형식을 쓴다:
    # "Fri Sep 18 15:25:02 2026". 시간대가 없으므로 UTC 로 본다 —
    # 컨테이너가 UTC 로 돈다.
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
