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

from redteam.tools import (
    STARTUP_FAILURE,
    ToolUnavailable,
    is_tool_case,
    tool_argv,
    unavailable,
)

MARKER_HEADER = "X-FSL-Case"
REQUEST_TIMEOUT = 15.0
TOOL_TIMEOUT = 600.0

                                                                                  
DEFAULT_TOOL_TARGET = "http://waf:8080"

_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")

class CaseRequestAltered(RuntimeError):
    pass

def load_cases(path: str | Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or []

def build_request(case: dict[str, Any], base_url: str) -> requests.PreparedRequest:
    spec = case["request"]
    headers: dict[str, str] = dict(spec.get("headers") or {})
    if case.get("correlation") == "marker":
        headers[MARKER_HEADER] = case["case_id"]

    return requests.Request(
        method=spec.get("method", "GET"),
        url=f"{base_url.rstrip('/')}{spec['path']}",
        headers=headers,
        json=spec.get("json"),
        params=spec.get("params"),
    ).prepare()

def check_path_preserved(declared_path: str, prepared_url: str) -> None:
    sent = _canonical_path(prepared_url)
    declared = _canonical_path(declared_path)
    if sent != declared:
        raise CaseRequestAltered(
            f"request path changed before sending: declared {declared!r} -> "
            f"sent {sent!r}. Ground truth would be false. Use `%2e%2e` instead of `..`."
        )

def _canonical_path(url_or_path: str) -> str:
    path = urlsplit(requote_uri(url_or_path)).path
    return _PERCENT_ESCAPE.sub(lambda m: "%" + m.group(1).upper(), path)

def case_meta(case: dict[str, Any]) -> dict[str, Any]:
    if is_tool_case(case):
        return {"tool": case["tool"], "args": list(case.get("args") or [])}
    return {"request": case["request"]}

def run(
    cases: list[dict[str, Any]],
    platform_url: str,
    target_url: str,
    launch,
    tool_target_url: str = DEFAULT_TOOL_TARGET,
) -> int:
    http = requests.Session()
    platform_url = platform_url.rstrip("/")
    session_id = _open_session(http, platform_url)

    for case in cases:
        case = dict(case)
        case.setdefault("case_id", str(uuid.uuid4()))
        case.setdefault("correlation", "marker")

        started_at = _now()
        fire(http, case, target_url, launch, tool_target_url)
        _record(http, platform_url, session_id, case, started_at, _now())

    http.post(
        f"{platform_url}/api/sessions/{session_id}/close/", timeout=REQUEST_TIMEOUT
    )
    return session_id

def _open_session(http: requests.Session, platform_url: str) -> int:
    response = http.post(
        f"{platform_url}/api/sessions/",
        json={"scenario": "juice-shop"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["id"]

def fire(
    http: requests.Session,
    case: dict[str, Any],
    target_url: str,
    launch,
    tool_target_url: str = DEFAULT_TOOL_TARGET,
) -> None:
    if is_tool_case(case):
        fire_tool(case, tool_target_url, launch)
        return

    prepared = build_request(case, target_url)

                                                                             
                          
    check_path_preserved(case["request"]["path"], prepared.url)

    try:
        http.send(prepared, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
                                                                       
                                                                        
        print(f"  ! {case['name']}: request failed - {exc}")

def fire_tool(case: dict[str, Any], target_url: str, launch) -> None:
    image, argv = tool_argv(case, target_url)
    try:
        result = launch(image, argv, timeout=TOOL_TIMEOUT)
    except OSError as exc:
        raise unavailable(case["name"], str(exc)) from exc

    if result.exit_code == STARTUP_FAILURE:
        raise unavailable(case["name"], result.output.strip()[:200])

    if result.exit_code != 0:
                                                                             
                                                                           
        print(f"  . {case['name']}: tool exited {result.exit_code}")

def _record(
    http: requests.Session,
    platform_url: str,
    session_id: int,
    case: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
) -> None:
    response = http.post(
        f"{platform_url}/api/sessions/{session_id}/cases/",
        json={
            "case_id": case["case_id"],
            "name": case["name"],
            "malicious": case["malicious"],
            **{key: case.get(key) or "" for key in ("stage", "technique", "pattern", "expect")},
            "correlation": case["correlation"],
            "source_ip": case.get("source_ip"),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "meta": case_meta(case),
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

def _now() -> datetime:
    return datetime.now(timezone.utc)
