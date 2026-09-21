from __future__ import annotations

import re

MARKER = "# fsl-suppressed"

def find(content: str, sid: int) -> str | None:
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.search(rf"\bsid\s*:\s*{sid}\b", line):
            return line
    return None

def silence(content: str, sid: int, until: str) -> str:
    line = find(content, sid)
    if line is None:
        raise KeyError(sid)
    return content.replace(line, f"{MARKER} until {until}\n#{line}", 1)

def restore(content: str, sid: int, original: str) -> str:
    commented = f"#{original}"
    if commented not in content:
                                                                         
                                 
        raise KeyError(sid)
    out = content.replace(commented, original, 1)
    return re.sub(rf"{re.escape(MARKER)} until [^\n]*\n", "", out, count=1)
