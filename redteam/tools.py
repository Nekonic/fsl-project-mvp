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
from urllib.parse import urlsplit

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl-kali")
TOOL_NETWORK = os.environ.get("FSL_TOOL_NETWORK", "fsl_edge")


def network_for(target_url: str) -> str:
    """The network to run the tool on: the segment it is about to attack from.

    The WAF answers on every origin under a name that says which one - so the
    host being dialled already names the network, and running the tool
    anywhere else would either fail to resolve it or send the attack from an
    address the case does not claim.
    """
    host = urlsplit(target_url).hostname or ""
    if not host.startswith("waf-"):
        return TOOL_NETWORK
    project = TOOL_NETWORK.split("_", 1)[0]
    return f"{project}_{host[len('waf-'):]}"

# Tool name -> the executable to run inside the container.
# Still one tool, and the reason is the marker rather than the image. A case
# is correlated by a header this appends as `--headers=`, which is sqlmap's
# syntax; nmap and nikto do not take it, so their traffic would carry no
# marker and be scored as undetected - a harness failure charged to the
# defence, which is the one mistake this platform must not make. The shell is
# where those tools are used, and a labelled window scores them properly.
# See docs/DECISIONS.md.
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

    # {target} is the URL; {target_host} is the host alone, for the tools that
    # take a host rather than a URL - nmap, netcat, hydra - which are also the
    # ones that ignore http_proxy.
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
