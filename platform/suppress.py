"""Silencing a Suricata rule, and putting it back. Pure text, no I/O.

A verdict that goes nowhere teaches nothing: every console lets an analyst
record "false positive" and none of them change the rule that produced it. The
range owns both sides, so here the verdict is the edit.

The edit is a comment, not a deletion, and the original line is kept verbatim
so that restoring it cannot drift.
"""

from __future__ import annotations

import re

MARKER = "# fsl-suppressed"


def find(content: str, sid: int) -> str | None:
    """The active rule line carrying this sid, if there is one."""
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.search(rf"\bsid\s*:\s*{sid}\b", line):
            return line
    return None


def silence(content: str, sid: int, until: str) -> str:
    """Comment the rule out, saying who did it and when it comes back.

    Commented rather than removed: a rule file that quietly loses lines is a
    rule file nobody can reason about, and the expiry has to be readable by
    whoever opens the file rather than only by the platform.
    """
    line = find(content, sid)
    if line is None:
        raise KeyError(sid)
    return content.replace(line, f"{MARKER} until {until}\n#{line}", 1)


def restore(content: str, sid: int, original: str) -> str:
    """Put the rule back exactly as it was, and take the marker with it."""
    commented = f"#{original}"
    if commented not in content:
        # Already back, by hand or by an earlier restore. Saying so beats
        # writing the line twice.
        raise KeyError(sid)
    out = content.replace(commented, original, 1)
    return re.sub(rf"{re.escape(MARKER)} until [^\n]*\n", "", out, count=1)
