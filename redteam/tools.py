from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl-kali")

SUPPORTED_TOOLS = {"sqlmap": "sqlmap"}

class UnsupportedTool(ValueError):
    pass

class ToolUnavailable(RuntimeError):
    pass

STARTUP_FAILURE = 125

def unavailable(case_name: str, detail: str) -> ToolUnavailable:
    return ToolUnavailable(
        f"{case_name}: the tool did not run ({TOOL_IMAGE}). {detail} "
        f"Build it first: docker compose build kali"
    )

def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))

def tool_argv(case: dict[str, Any], target_url: str) -> tuple[str, list[str]]:
    tool = case["tool"]
    executable = SUPPORTED_TOOLS.get(tool)
    if executable is None:
        raise UnsupportedTool(
            f"{tool!r} is not supported. Supported tools: "
            f"{', '.join(sorted(SUPPORTED_TOOLS))}"
        )

    host = urlsplit(target_url).hostname or ""
    args = [
        str(a).replace("{target}", target_url.rstrip("/")).replace("{target_host}", host)
        for a in case["args"]
    ]

    if case.get("correlation") == "marker":
        args.append(f"--headers={MARKER_HEADER}: {case['case_id']}")

    return TOOL_IMAGE, [executable, *args]
