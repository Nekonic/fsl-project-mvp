"""공격·정상 트래픽을 보내고 ground truth 를 platform 에 기록한다.

케이스마다 X-FSL-Case 헤더를 실어 보내는 것이 채점의 전부다. 실제
공격자는 이런 마커를 달아주지 않지만, ground truth 를 만드는 쪽은
플랫폼이 통제하므로 성립한다. 이것은 훈련 환경의 채점 장치이지
탐지 기법이 아니다.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
import yaml
from requests.utils import requote_uri

MARKER_HEADER = "X-FSL-Case"
REQUEST_TIMEOUT = 15.0


_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")


class CaseRequestAltered(RuntimeError):
    """요청이 선언한 경로와 다르게 나갔다. ground truth 가 거짓이 된다."""


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """YAML 케이스 파일을 읽는다."""
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or []


def build_request(case: dict[str, Any], base_url: str) -> dict[str, Any]:
    """케이스 하나를 requests 호출 인자로 바꾼다.

    마커 대응 케이스에만 헤더를 싣는다. 시간창 케이스에 마커가 달리면
    두 전략이 섞여 대응 실패가 보이지 않게 된다.
    """
    spec = case["request"]
    headers: dict[str, str] = dict(spec.get("headers") or {})
    if case.get("correlation") == "marker":
        headers[MARKER_HEADER] = case["case_id"]

    return {
        "method": spec.get("method", "GET"),
        "url": f"{base_url.rstrip('/')}{spec['path']}",
        "headers": headers,
        "json": spec.get("json"),
        "params": spec.get("params"),
    }


def check_path_preserved(declared_path: str, prepared_url: str) -> None:
    """선언한 경로가 그대로 전송되는지 확인한다.

    requests 는 `/ftp/../../../../etc/passwd` 를 `/etc/passwd` 로 정규화해서
    보낸다. 경로 탐색 공격이 전송되지 않았는데 ground truth 에는 "공격을
    보냈다" 고 남으면 채점이 거짓말을 한다. 미탐으로 집계되지만 실제로는
    방어가 아니라 하니스가 실패한 것이다. 조용히 넘어가서는 안 된다.

    우회하려면 `..` 대신 `%2e%2e` 를 쓴다 — 전송은 그대로 되고 WAF·IDS 는
    똑같이 경로 탐색으로 본다.
    """
    sent = _canonical_path(prepared_url)
    declared = _canonical_path(declared_path)
    if sent != declared:
        raise CaseRequestAltered(
            f"요청 경로가 전송 전에 바뀌었다: 선언 {declared!r} -> 전송 {sent!r}. "
            f"ground truth 가 거짓이 된다. `..` 를 `%2e%2e` 로 바꾸라."
        )


def _canonical_path(url_or_path: str) -> str:
    """구조 변화만 보이도록 경로를 정규화한다.

    퍼센트 인코딩의 표기 차이는 무시한다 — requests 는 `%2e` 를 `.` 로
    풀고 `%2f` 를 `%2F` 로 다시 쓴다. 둘 다 RFC 3986 상 같은 경로다.
    잡아야 하는 것은 `..` 세그먼트가 통째로 사라지는 구조적 재작성이다.
    """
    path = urlsplit(requote_uri(url_or_path)).path
    return _PERCENT_ESCAPE.sub(lambda m: "%" + m.group(1).upper(), path)


class Harness:
    """세션을 열고 케이스를 실행한 뒤 ground truth 를 기록한다."""

    def __init__(
        self,
        platform_url: str,
        target_url: str,
        session: requests.Session | None = None,
    ) -> None:
        self.platform_url = platform_url.rstrip("/")
        self.target_url = target_url.rstrip("/")
        self.session = session or requests.Session()

    def run(self, cases: list[dict[str, Any]]) -> int:
        session_id = self._open_session()

        for case in cases:
            case = dict(case)
            case.setdefault("case_id", str(uuid.uuid4()))
            case.setdefault("correlation", "marker")

            started_at = _now()
            self._fire(case)
            ended_at = _now()

            self._record(session_id, case, started_at, ended_at)

        self._close_session(session_id)
        return session_id

    def _open_session(self) -> int:
        response = self.session.post(
            f"{self.platform_url}/api/sessions/",
            json={"scenario": "juice-shop"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["id"]

    def _close_session(self, session_id: int) -> None:
        self.session.post(
            f"{self.platform_url}/api/sessions/{session_id}/close/",
            timeout=REQUEST_TIMEOUT,
        )

    def _fire(self, case: dict[str, Any]) -> None:
        spec = build_request(case, self.target_url)
        prepared = requests.Request(
            method=spec["method"],
            url=spec["url"],
            headers=spec["headers"],
            json=spec["json"],
            params=spec["params"],
        ).prepare()

        # 선언한 것과 다른 요청이 나가면 ground truth 가 거짓이 된다.
        # 이건 삼키지 않고 터뜨린다.
        check_path_preserved(case["request"]["path"], prepared.url)

        try:
            self.session.send(prepared, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            # 대상이 4xx/5xx 를 내거나 연결이 끊겨도 ground truth 는 남겨야
            # 한다. 요청이 나갔다는 사실 자체가 채점 대상이다.
            print(f"  ! {case['name']}: 요청 실패 — {exc}")

    def _record(
        self,
        session_id: int,
        case: dict[str, Any],
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        payload = {
            "case_id": case["case_id"],
            "name": case["name"],
            "malicious": bool(case["malicious"]),
            "technique": case.get("technique") or "",
            "correlation": case["correlation"],
            "source_ip": case.get("source_ip"),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "meta": {"request": case["request"]},
        }
        response = self.session.post(
            f"{self.platform_url}/api/sessions/{session_id}/cases/",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()


def _now() -> datetime:
    return datetime.now(timezone.utc)
