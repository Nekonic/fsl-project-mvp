from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings

_TIMEOUT = 15

class ObjectivesUnavailable(RuntimeError):
    """The target is not answering, so nothing can be said about objectives."""

                                                                               
                                                               
INTERNAL = {
    "key": "internalRunbookRead",
    "name": "Internal runbook read",
    "category": "Lateral Movement",
    "difficulty": 6,
    "description": (
        "Read the estate's internal wiki, which is reachable from the "
        "application and from nowhere else."
    ),
}

def catalogue() -> list[dict[str, Any]]:
    return [_summarise(challenge) for challenge in _fetch()] + [_internal()]

def solved_keys() -> set[str]:
    taken = {c["key"] for c in _fetch() if c.get("solved")}
    if _internal()["solved"]:
        taken.add(INTERNAL["key"])
    return taken

def _internal() -> dict[str, Any]:
    when = None
    try:
        for line in Path(settings.WIKI_READ_LOG).read_text().splitlines():
            stamp, _, rest = line.partition(" ")
            if settings.WIKI_SECRET_PATH in rest:
                when = stamp
    except OSError:
                                                                            
                                                                  
        pass

    return dict(INTERNAL, solved=bool(when), solved_at=when)

def _fetch() -> list[dict[str, Any]]:
    url = f"{settings.WARGAME_API_URL.rstrip('/')}/api/Challenges/"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:
            body = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ObjectivesUnavailable(
            f"could not read objectives from {url}: {exc}"
        ) from exc

    challenges = body.get("data") if isinstance(body, dict) else body
    if not isinstance(challenges, list):
        raise ObjectivesUnavailable(f"{url} did not return a challenge list")
    return challenges

def _summarise(challenge: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": challenge["key"],
        "name": challenge["name"],
        "category": challenge.get("category") or "",
        "difficulty": int(challenge.get("difficulty") or 1),
        "description": challenge.get("description") or "",
        "solved": bool(challenge.get("solved")),
                                                                           
                                                                           
                                                                      
                                                                       
        "solved_at": challenge.get("updatedAt") or None,
    }
