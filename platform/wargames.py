from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

import lifecycle
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
    return [
        {
            "name": case["name"],
            "malicious": bool(case["malicious"]),
            "stage": case.get("stage") or "",
            "technique": case.get("technique") or "",
            "pattern": case.get("pattern") or "",
            "references": _references(case),
            "correlation": case.get("correlation") or "marker",
            "expect": case.get("expect") or "",
            "takes": case.get("takes") or "",
            "summary": _summary(case),
        }
        for case in _load(wargame_id)
    ]

def _references(case: dict[str, Any]) -> dict[str, str]:
    found = {
        field: lifecycle.reference(case.get(field) or "")
        for field in ("technique", "pattern")
    }
    return {field: url for field, url in found.items() if url}

def expectations(wargame_id: str) -> dict[str, str]:
    return {case["name"]: case.get("expect") or "" for case in _load(wargame_id)}

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
    loaded = _load(wargame["id"])
    reached = {case.get("stage") for case in loaded}
    return {
        "id": wargame["id"],
        "name": wargame["name"],
        "description": wargame["description"],
        "cases": len(loaded),
        "covers": [stage for stage in lifecycle.STAGES if stage in reached],
        "uncovered": [stage for stage in lifecycle.STAGES if stage not in reached],
    }

def _summary(case: dict[str, Any]) -> str:
    if is_tool_case(case):
        return " ".join([case["tool"], *(case.get("args") or [])])
    request = case["request"]
    return f"{request.get('method', 'GET')} {request['path']}"
