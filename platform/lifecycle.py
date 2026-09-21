from __future__ import annotations

import re

STAGES = (
    "initial-reconnaissance",
    "initial-compromise",
    "establish-foothold",
    "escalate-privileges",
    "internal-reconnaissance",
    "move-laterally",
    "maintain-presence",
    "complete-mission",
)

_TECHNIQUE = re.compile(r"^T(\d{4})(?:\.(\d{3}))?$")
_PATTERN = re.compile(r"^CAPEC-(\d+)$")

def reference(identifier: str) -> str:
    technique = _TECHNIQUE.match(identifier or "")
    if technique:
        parent, sub = technique.groups()
        tail = f"{parent}/{sub}/" if sub else f"{parent}/"
        return f"https://attack.mitre.org/techniques/T{tail}"

    pattern = _PATTERN.match(identifier or "")
    if pattern:
        return f"https://capec.mitre.org/data/definitions/{pattern.group(1)}.html"

    return ""
