from __future__ import annotations

import re

MARKER = "# fsl-suppressed"
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"')
_SID = re.compile(r"[(;]\s*sid\s*:\s*(\d+)\s*[;)]")

def find(content: str, sid: int) -> str | None:
    lines = content.splitlines()
    at = _active(lines, sid)
    return None if at is None else lines[at]

def silence(content: str, sid: int, until: str) -> str:
    lines = content.splitlines(keepends=True)
    at = _active(lines, sid)
    if at is None:
        raise KeyError(sid)
    lines[at] = f"{MARKER} until {until}\n#{lines[at]}"
    return "".join(lines)

def restore(content: str, sid: int, original: str) -> str:
    lines, at = _silenced(content, sid, original)
    lines[at] = lines[at][1:]
    del lines[at - 1]
    return "".join(lines)

def discard(content: str, sid: int, original: str) -> str:
    lines, at = _silenced(content, sid, original)
    del lines[at - 1:at + 1]
    return "".join(lines)

def _silenced(content: str, sid: int, original: str) -> tuple[list[str], int]:
    lines = content.splitlines(keepends=True)
    for at in range(1, len(lines)):
        marked = lines[at - 1].startswith(f"{MARKER} until ")
        if marked and lines[at].rstrip("\r\n") == f"#{original}" and _sid(lines[at]) == sid:
            return lines, at
    raise KeyError(sid)

def _active(lines: list[str], sid: int) -> int | None:
    for at, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith("#") and _sid(line) == sid:
            return at
    return None

def _sid(rule: str) -> int | None:
    option = _SID.search(_QUOTED.sub('""', rule))
    return int(option[1]) if option else None
