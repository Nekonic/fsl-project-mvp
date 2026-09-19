"""Send attack and benign traffic, and record ground truth on the platform.

Scoring rests entirely on sending an X-FSL-Case header with every case. A real
attacker would not label their traffic, but the side that produces ground truth
is the platform itself, so this holds. It is a scoring device for a training
range, not a detection technique.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
import yaml
from requests.utils import requote_uri

from redteam.tools import (
    DOCKER_STARTUP_FAILURE,
    TOOL_IMAGE,
    ToolUnavailable,
    build_tool_command,
    is_tool_case,
)

MARKER_HEADER = "X-FSL-Case"
REQUEST_TIMEOUT = 15.0
TOOL_TIMEOUT = 600.0

# Tool containers run inside the stack network, where localhost is not the target.
DEFAULT_TOOL_TARGET = "http://waf:8080"


_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")


class CaseRequestAltered(RuntimeError):
    """The request went out differently than declared, so ground truth is false."""


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Read a YAML case file."""
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or []


def build_request(case: dict[str, Any], base_url: str) -> requests.PreparedRequest:
    """Turn one case into the request that will actually go on the wire.

    Prepared rather than sent, so a test can pin down exactly what would leave.

    Only marker-correlated cases carry the header. Putting a marker on a window
    case would blend the two strategies and hide correlation failures.
    """
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
    """Check that the declared path is what actually goes on the wire.

    requests normalises `/ftp/../../../../etc/passwd` to `/etc/passwd` before
    sending. If the traversal never left but ground truth records "attack sent",
    the score lies: it counts as a miss when in fact the harness, not the
    defence, failed. That must not pass quietly.

    Write `%2e%2e` instead of `..` to get around it - it is sent verbatim and
    the WAF and IDS still read it as traversal.
    """
    sent = _canonical_path(prepared_url)
    declared = _canonical_path(declared_path)
    if sent != declared:
        raise CaseRequestAltered(
            f"request path changed before sending: declared {declared!r} -> "
            f"sent {sent!r}. Ground truth would be false. Use `%2e%2e` instead of `..`."
        )


def _canonical_path(url_or_path: str) -> str:
    """Normalise a path so only structural changes show.

    Differences in percent-encoding are ignored: requests decodes `%2e` to `.`
    and re-encodes `%2f` as `%2F`, and RFC 3986 calls those the same path. What
    must be caught is structural rewriting, where `..` segments disappear.
    """
    path = urlsplit(requote_uri(url_or_path)).path
    return _PERCENT_ESCAPE.sub(lambda m: "%" + m.group(1).upper(), path)


def case_meta(case: dict[str, Any]) -> dict[str, Any]:
    """Summarise what a case did, for the record.

    Tool cases have no `request`. Blowing up here would abort the whole session
    with no ground truth at all.
    """
    if is_tool_case(case):
        return {"tool": case["tool"], "args": list(case.get("args") or [])}
    return {"request": case["request"]}


def run(
    cases: list[dict[str, Any]],
    platform_url: str,
    target_url: str,
    tool_target_url: str = DEFAULT_TOOL_TARGET,
) -> int:
    """Open a session, run every case, record ground truth, close the session.

    One requests.Session for the whole run, so the traffic keeps HTTP
    keep-alive - which is what the (flow_id, tx_id) correlation has to cope
    with, and therefore what this has to reproduce.
    """
    http = requests.Session()
    platform_url = platform_url.rstrip("/")
    session_id = _open_session(http, platform_url)

    for case in cases:
        case = dict(case)
        case.setdefault("case_id", str(uuid.uuid4()))
        case.setdefault("correlation", "marker")

        started_at = _now()
        fire(http, case, target_url, tool_target_url)
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
    tool_target_url: str,
) -> None:
    """Send one case's traffic."""
    if is_tool_case(case):
        fire_tool(case, tool_target_url)
        return

    prepared = build_request(case, target_url)

    # A request that differs from what was declared makes ground truth false.
    # Do not swallow this.
    check_path_preserved(case["request"]["path"], prepared.url)

    try:
        http.send(prepared, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        # Record ground truth even if the target answers 4xx/5xx or the
        # connection drops. That the request went out is what is scored.
        print(f"  ! {case['name']}: request failed - {exc}")


def fire_tool(case: dict[str, Any], tool_target_url: str) -> None:
    command = build_tool_command(case, tool_target_url)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=TOOL_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolUnavailable(
            f"{case['name']}: could not run the tool - {exc}. "
            f"Build the image first: docker compose --profile tools build"
        ) from exc

    if result.returncode == DOCKER_STARTUP_FAILURE:
        raise ToolUnavailable(
            f"{case['name']}: the tool container did not start "
            f"({TOOL_IMAGE}). {result.stderr.strip()[:200]} "
            f"Build the image first: docker compose --profile tools build"
        )

    if result.returncode != 0:
        # The tool exiting non-zero is normal: sqlmap does that when it finds
        # no injection point. The attempt went out, so ground truth stands.
        print(f"  . {case['name']}: tool exited {result.returncode}")


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
            "malicious": bool(case["malicious"]),
            "technique": case.get("technique") or "",
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
