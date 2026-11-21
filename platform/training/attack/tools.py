from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cr.errors import NotFound, Unavailable

MARKER_HEADER = "X-Request-ID"
STATUS = re.compile(r"http_code=(\d{3})")
FORBIDDEN = re.compile(r"403 \(Forbidden\) - (\d+) times")
TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
ENDED = "[*] ending @"
NOT_INJECTABLE = "all tested parameters do not appear to be injectable"
CONCLUSION = re.compile(
    r"(?:seem|appear) to be injectable|appears to be '.*' injectable|identified the following injection point"
    r"|\[CRITICAL\] (?:all tested|host |heuristics detected)"
)
STAMP = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] ")
CONCLUSIONS_KEPT = 4
LINE_KEPT = 160
ABORTED = re.compile(r"\[CRITICAL\][^\n]*does not exist|Traceback|user (quit|aborted)", re.IGNORECASE)

FREE_TOOLS = ("curl", "dirb", "ffuf", "gobuster", "hydra", "nikto", "nmap", "sqlmap", "whatweb")
MOST_ARGS = 64
LONGEST_ARG = 4096


class ToolUnavailable(Unavailable):
    code = "tool_unavailable"


class UnknownTool(NotFound):
    code = "unknown_tool"

STARTUP_FAILURE = 125

def unavailable(case_name: str, detail: str) -> ToolUnavailable:
    return ToolUnavailable(
        f"{case_name}: the tool did not run on the attacker box. {detail}"
    )

def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))

def dumps(case: dict[str, Any]) -> bool:
    return "--dump" in (case.get("args") or [])

def fetch_argv(url: str, timeout: float, headers: dict | None = None) -> list[str]:
    argv = ["curl", "-sS", "-i", "--max-time", str(int(timeout))]
    for name, value in (headers or {}).items():
        argv += ["-H", f"{name}: {value}"]
    argv.append(url)
    return argv

PLACEHOLDER = re.compile(r"\{(\w+)\}")

def _inject(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda found: tokens.get(found[1], found[0]), value)
    if isinstance(value, dict):
        return {key: _inject(item, tokens) for key, item in value.items()}
    if isinstance(value, list):
        return [_inject(item, tokens) for item in value]
    return value

def apply_prefetch(case: dict[str, Any], base_url: str, launch, timeout: float) -> dict[str, Any]:
    spec = (case.get("request") or {}).get("prefetch")
    if not spec:
        return case
    headers = {name: value for name, value in ((case.get("request") or {}).get("headers") or {}).items()
               if not PLACEHOLDER.search(str(value))}
    argv = fetch_argv(f"{base_url.rstrip('/')}{spec['from']}", timeout, headers)
    try:
        result = launch(argv, timeout=timeout)
    except OSError as exc:
        raise unavailable(case["name"], str(exc)) from exc
    if result.exit_code != 0:
        raise ToolUnavailable(
            f"{case['name']}: the prefetch GET {spec['from']} never reached the target "
            f"(curl exit {result.exit_code}): {result.output.strip()[:200]}"
        )
    found = re.search(spec["pattern"], result.output or "")
    if not found:
        raise ToolUnavailable(
            f"{case['name']}: the token {spec['pattern']!r} was not on {spec['from']}, "
            f"so the request would carry no nonce and the target would reject it."
        )
    request = {key: value for key, value in case["request"].items() if key != "prefetch"}
    return dict(case, request=_inject(request, {"nonce": found.group(1), **found.groupdict()}))

def curl_argv(prepared: Any, timeout: float) -> list[str]:
    argv = [
        "curl", "-sS", "-o", "/dev/null", "-w", "http_code=%{http_code}\n",
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
    return argv

def tool_argv(case: dict[str, Any], target_url: str, runs: str | None = None) -> list[str]:
    host = urlsplit(target_url).hostname or ""
    args = [
        str(a).replace("{target}", target_url.rstrip("/")).replace("{target_host}", host)
        for a in case["args"]
    ]

    if case.get("correlation") == "marker":
        args.append(f"--headers={MARKER_HEADER}: {case['case_id']}")
        if case["tool"] == "sqlmap" and runs:
            args.append(f"--output-dir={runs}/{case['case_id']}")

    return [case["tool"], *args]


def free_argv(tool: str, args: list[str], marker: str | None = None) -> list[str]:
    if tool not in FREE_TOOLS:
        raise UnknownTool(f"no tool {tool!r}; the box offers {list(FREE_TOOLS)}")
    if not isinstance(args, list) or len(args) > MOST_ARGS or not all(
            isinstance(arg, str) and len(arg) <= LONGEST_ARG and "\x00" not in arg for arg in args):
        raise ValueError(f"args is a list of at most {MOST_ARGS} strings of at most {LONGEST_ARG} characters")
    marked = []
    if marker and tool == "curl":
        marked = ["-H", f"{MARKER_HEADER}: {marker}"]
    elif marker and tool == "sqlmap":
        marked = [f"--headers={MARKER_HEADER}: {marker}"]
    return [tool, *marked, *args]

def status(output: str) -> int:
    found = STATUS.findall(output if isinstance(output, str) else "")
    return int(found[-1]) if found else 0

def forbidden(output: str) -> int:
    return sum(int(times) for times in FORBIDDEN.findall(output or ""))

def conclusions(output: str) -> list[str]:
    found = [STAMP.sub("", line).strip() for line in (output or "").splitlines() if CONCLUSION.search(line)]
    return [line if len(line) <= LINE_KEPT else line[:LINE_KEPT] + "…" for line in found[-CONCLUSIONS_KEPT:]]

def dumped(output: str) -> list[tuple[str, str]]:
    rows = [
        [cell.strip() for cell in found[1].split("|")]
        for found in map(TABLE_ROW.match, (output or "").splitlines()) if found
    ]
    header = next((row for row in rows if "username" in row and "password" in row), None)
    if header is None:
        return []
    name, digest = header.index("username"), header.index("password")
    return [
        (row[name], row[digest]) for row in rows
        if row != header and len(row) == len(header)
    ]

SENT_STATUS = "cr.status="
REQUEST_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
HEADER_END = "\r\n\r\n"


@dataclass(frozen=True)
class Answer:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: str


def request_argv(method: str, url: str, headers: dict[str, str], has_body: bool, timeout: float,
                 interface: str = "") -> list[str]:
    if method not in REQUEST_METHODS:
        raise ValueError(f"method is one of {list(REQUEST_METHODS)}")
    argv = ["curl", "-sS", "-i", "--path-as-is", "--max-time", str(int(timeout)), "-X", method,
            "-H", "Expect:", "-w", f"\n{SENT_STATUS}%{{http_code}}\n"]
    if interface:
        argv += ["--interface", interface]
    for name, value in headers.items():
        argv += ["-H", f"{name}: {value}"]
    if has_body:
        argv += ["--data-binary", "@-"]
    argv.append(url)
    return argv


def answered(output: str) -> Answer:
    head, found, code = (output or "").rpartition(f"\n{SENT_STATUS}")
    status = int(code.strip()) if found and code.strip().isdigit() else 0
    if not status:
        return Answer(status=0, headers=(), body="")
    raw, gap, body = head.partition(HEADER_END)
    lines = raw.split("\r\n")[1:] if gap else []
    headers = tuple((name.strip(), value.strip()) for name, colon, value in (line.partition(":") for line in lines)
                    if colon)
    return Answer(status=status, headers=headers, body=body if gap else head)


def found_not_injectable(exit_code: int, output: str) -> bool:
    output = output if isinstance(output, str) else ""
    return (
        exit_code == 0 and ENDED in output and not ABORTED.search(output)
        and NOT_INJECTABLE in output and not dumped(output)
    )
