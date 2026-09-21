from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl-kali")
TOOL_NETWORK = os.environ.get("FSL_TOOL_NETWORK", "fsl_edge")

def network_for(target_url: str) -> str:
    host = urlsplit(target_url).hostname or ""
    if not host.startswith("waf-"):
        return TOOL_NETWORK
    project = TOOL_NETWORK.split("_", 1)[0]
    return f"{project}_{host[len('waf-'):]}"

                                                          
                                                                            
                                                                           
                                                                        
                                                                       
                                                                             
                                                                         
 
SUPPORTED_TOOLS = {"sqlmap": "sqlmap"}

class UnsupportedTool(ValueError):
    """The case declared a tool this MVP does not know."""

class ToolUnavailable(RuntimeError):
    """The tool never ran, so no attack went out and ground truth is false.

    Counting that as a miss records a harness failure as a defence failure.
    """

                                                                           
                                                                           
DOCKER_STARTUP_FAILURE = 125

def unavailable(case_name: str, detail: str) -> ToolUnavailable:
    return ToolUnavailable(
        f"{case_name}: the tool did not run ({TOOL_IMAGE}). {detail} "
        f"Build it first: docker compose build kali"
    )

def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))

def build_tool_command(case: dict[str, Any], target_url: str) -> list[str]:
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

    return [
        "docker",
        "run",
        "--rm",
        "--network",
        network_for(target_url),
        TOOL_IMAGE,
        executable,
        *args,
    ]
