from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
import yaml
from requests.utils import requote_uri

from attack.tools import (
    MARKER_HEADER,
    STARTUP_FAILURE,
    ToolUnavailable,
    apply_prefetch,
    curl_argv,
    is_tool_case,
    tool_argv,
    unavailable,
)

REQUEST_TIMEOUT = 15.0
TOOL_TIMEOUT = 600.0

_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")

Launch = Callable[..., Any]


class CaseRequestAltered(ValueError):
    pass


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []


def build_request(case: dict[str, Any], base_url: str, marker: str | None = None) -> requests.PreparedRequest:
    spec = case["request"]
    headers: dict[str, str] = dict(spec.get("headers") or {})
    if marker or case.get("correlation") == "marker":
        headers[MARKER_HEADER] = marker or case["case_id"]

    return requests.Request(
        method=spec.get("method", "GET"),
        url=f"{base_url.rstrip('/')}{spec['path']}",
        headers=headers,
        json=spec.get("json"),
        data=spec.get("data"),
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


def fire(case: dict[str, Any], launch: Launch, target_url: str, runs: str | None = None,
         marker: str | None = None):
    if marker:
        case = dict(case, case_id=marker, correlation="marker")
    if is_tool_case(case):
        return fire_tool(case, target_url, launch, runs)
    case = apply_prefetch(case, target_url, launch, REQUEST_TIMEOUT)
    prepared = build_request(case, target_url)
    check_path_preserved(case["request"]["path"], prepared.url)
    return fire_http(case, prepared, launch)


def _on_attacker(case: dict[str, Any], argv: list[str], launch: Launch):
    try:
        return launch(argv, timeout=TOOL_TIMEOUT)
    except OSError as exc:
        raise unavailable(case["name"], str(exc)) from exc


def fire_http(case: dict[str, Any], prepared: requests.PreparedRequest, launch: Launch):
    result = _on_attacker(case, curl_argv(prepared, REQUEST_TIMEOUT), launch)
    if result.exit_code != 0:
        raise ToolUnavailable(f"{case['name']}: the request never reached the target "
                              f"from the attacker box (curl exit {result.exit_code}): {result.output.strip()[:200]}")
    return result


def fire_tool(case: dict[str, Any], target_url: str, launch: Launch, runs: str | None = None):
    result = _on_attacker(case, tool_argv(case, target_url, runs), launch)
    if result.exit_code == STARTUP_FAILURE:
        raise unavailable(case["name"], result.output.strip()[:200])
    return result
