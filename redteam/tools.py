from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl/kali:mvp")

class ToolUnavailable(RuntimeError):
    pass

STARTUP_FAILURE = 125

def unavailable(case_name: str, detail: str) -> ToolUnavailable:
    return ToolUnavailable(
        f"{case_name}: the tool did not run ({TOOL_IMAGE}). {detail} "
        f"Build it first: docker compose -f session.yaml build kali"
    )

def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))

def fetch_argv(url: str, timeout: float) -> tuple[str, list[str]]:
    return TOOL_IMAGE, ["curl", "-sS", "--max-time", str(int(timeout)), url]

def _inject(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace("{nonce}", token)
    if isinstance(value, dict):
        return {key: _inject(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [_inject(item, token) for item in value]
    return value

def apply_prefetch(case: dict[str, Any], base_url: str, launch, timeout: float) -> dict[str, Any]:
    spec = (case.get("request") or {}).get("prefetch")
    if not spec:
        return case
    image, argv = fetch_argv(f"{base_url.rstrip('/')}{spec['from']}", timeout)
    try:
        body = launch(image, argv, timeout=timeout).output
    except OSError as exc:
        raise unavailable(case["name"], str(exc)) from exc
    found = re.search(spec["pattern"], body or "")
    if not found:
        raise ToolUnavailable(
            f"{case['name']}: the token {spec['pattern']!r} was not on {spec['from']}, "
            f"so the request would carry no nonce and the target would reject it."
        )
    request = {key: value for key, value in case["request"].items() if key != "prefetch"}
    return dict(case, request=_inject(request, found.group(1)))

def curl_argv(prepared: Any, timeout: float) -> tuple[str, list[str]]:
    argv = [
        "curl", "-sS", "-o", "/dev/null",
        "--max-time", str(int(timeout)), "--path-as-is",
        "-X", prepared.method or "GET",
    ]
    for name, value in prepared.headers.items():
        if name.lower() != "content-length":
            argv += ["-H", f"{name}: {value}"]
    if prepared.body is not None:
        body = prepared.body
        argv += ["--data-binary", body.decode() if isinstance(body, bytes) else body]
    argv.append(prepared.url)
    return TOOL_IMAGE, argv

def tool_argv(case: dict[str, Any], target_url: str) -> tuple[str, list[str]]:
    host = urlsplit(target_url).hostname or ""
    args = [
        str(a).replace("{target}", target_url.rstrip("/")).replace("{target_host}", host)
        for a in case["args"]
    ]

    if case.get("correlation") == "marker":
        args.append(f"--headers={MARKER_HEADER}: {case['case_id']}")

    return TOOL_IMAGE, [case["tool"], *args]
