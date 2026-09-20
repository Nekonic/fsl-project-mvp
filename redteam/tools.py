"""Run external attack tools as one-shot containers.

When a case declares `tool:`, the harness hands it here instead of making the
HTTP request itself. The tool joins the stack network, so it addresses the
target by container name rather than localhost: a case writes the `{target}`
placeholder and the harness substitutes the internal address.

This MVP supports one tool, sqlmap. Correlating ground truth requires injecting
the marker header, and `--headers` is the only mechanism available. Non-HTTP
tools such as nmap need window correlation instead, which requires knowing the
tool container's IP.
"""

from __future__ import annotations

import os
from typing import Any

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl-redteam-tools")
TOOL_NETWORK = os.environ.get("FSL_TOOL_NETWORK", "fsl_edge")

# Tool name -> the executable to run inside the container.
SUPPORTED_TOOLS = {"sqlmap": "sqlmap"}


class UnsupportedTool(ValueError):
    """The case declared a tool this MVP does not know."""


class ToolUnavailable(RuntimeError):
    """The tool never ran, so no attack went out and ground truth is false.

    Counting that as a miss records a harness failure as a defence failure.
    """


# What docker returns when it could not even start the container. Must stay
# distinct from the tool's own non-zero exit (sqlmap finding no injection).
DOCKER_STARTUP_FAILURE = 125


def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))


def build_tool_command(case: dict[str, Any], target_url: str) -> list[str]:
    """Turn a case into a `docker run` argv.

    Builds without running, so what will be executed can be pinned by tests.
    """
    tool = case["tool"]
    executable = SUPPORTED_TOOLS.get(tool)
    if executable is None:
        raise UnsupportedTool(
            f"{tool!r} is not supported. Supported tools: "
            f"{', '.join(sorted(SUPPORTED_TOOLS))}"
        )

    args = [str(a).replace("{target}", target_url.rstrip("/")) for a in case["args"]]

    if case.get("correlation") == "marker":
        args.append(f"--headers={MARKER_HEADER}: {case['case_id']}")

    return [
        "docker",
        "run",
        "--rm",
        "--network",
        TOOL_NETWORK,
        TOOL_IMAGE,
        executable,
        *args,
    ]
