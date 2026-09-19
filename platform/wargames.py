"""The wargame catalogue: what can be attacked, and with which cases.

The case files are the red team harness's own, so a button in the console
fires exactly the traffic the CLI would. One definition, two callers - the
moment they diverge, the console stops testing what the harness tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from redteam.harness import is_tool_case, load_cases

WARGAMES = {
    "juice-shop": {
        "id": "juice-shop",
        "name": "OWASP Juice Shop",
        "description": "A deliberately insecure shop, behind the WAF and the IDS.",
        "case_file": "default.yaml",
    }
}


class UnknownWargame(KeyError):
    """Asked for a wargame that is not in the catalogue."""


def catalogue() -> list[dict[str, Any]]:
    return [_summarise(wargame) for wargame in WARGAMES.values()]


def cases(wargame_id: str) -> list[dict[str, Any]]:
    """Every case that can be fired, described well enough to put on a button."""
    return [
        {
            "name": case["name"],
            "malicious": bool(case["malicious"]),
            "technique": case.get("technique") or "",
            "correlation": case.get("correlation") or "marker",
            "summary": _summary(case),
        }
        for case in _load(wargame_id)
    ]


def find_case(wargame_id: str, name: str) -> dict[str, Any]:
    for case in _load(wargame_id):
        if case["name"] == name:
            return case
    raise UnknownWargame(name)


def _load(wargame_id: str) -> list[dict[str, Any]]:
    if wargame_id not in WARGAMES:
        raise UnknownWargame(wargame_id)
    path = Path(settings.WARGAME_CASES_DIR) / WARGAMES[wargame_id]["case_file"]
    return load_cases(path)


def _summarise(wargame: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": wargame["id"],
        "name": wargame["name"],
        "description": wargame["description"],
        "cases": len(_load(wargame["id"])),
    }


def _summary(case: dict[str, Any]) -> str:
    """What this case actually sends, short enough for a button."""
    if is_tool_case(case):
        return " ".join([case["tool"], *(case.get("args") or [])])
    request = case["request"]
    return f"{request.get('method', 'GET')} {request['path']}"
