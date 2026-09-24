from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings

from range.ports import RangeUnavailable

_TIMEOUT = 15
_SERVED = re.compile(r'(?P<at>\S+) 2\d\d "(?P<uri>[^"]*)"')

class ObjectivesUnavailable(RuntimeError):
    pass

                                                                               
                                                               
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

CHECKED_ON_A_LATER_REQUEST = frozenset({
    "changeProductChallenge",
    "feedbackChallenge",
    "knownVulnerableComponentChallenge",
    "weirdCryptoChallenge",
    "typosquattingNpmChallenge",
    "typosquattingAngularChallenge",
    "hiddenImageChallenge",
    "supplyChainAttackChallenge",
    "dlpPastebinDataLeakChallenge",
    "csafChallenge",
    "leakedApiKeyChallenge",
    "vulnerableDockerImageChallenge",
    "systemPromptExtractionChallenge",
})

def catalogue(wiki=None) -> list[dict[str, Any]]:
    found, unreadable = observe(wiki)
    if unreadable:
        found.append(dict(INTERNAL, solved=None, solved_at=None, unreadable=unreadable))
    return found

def observe(wiki=None) -> tuple[list[dict[str, Any]], str]:
    found = [_summarise(c) for c in _fetch()]
    try:
        found.append(_internal(wiki))
    except ObjectivesUnavailable as exc:
        return found, str(exc)
    return found, ""

def solved_keys(wiki=None) -> set[str]:
    taken = {c["key"] for c in _fetch() if c.get("solved")}
    if _internal(wiki)["solved"]:
        taken.add(INTERNAL["key"])
    return taken

def wiki_read_at(wiki, secret_path: str) -> str | None:
    ran = wiki(["cat", settings.WIKI_READ_LOG])
    if not ran.ok:
        if "No such file" in ran.output:
            return None
        raise ObjectivesUnavailable(
            f"could not read the wiki's access log: {ran.output.strip()[-200:]}"
        )

    when = None
    for line in ran.output.splitlines():
        served = _SERVED.match(line.lstrip("\0"))
        if served and served["uri"] == secret_path:
            when = served["at"]
    return when

def _internal(wiki=None) -> dict[str, Any]:
    when = None
    try:
        if wiki is not None:
            when = wiki_read_at(wiki, settings.WIKI_SECRET_PATH)
    except RangeUnavailable as exc:
        raise ObjectivesUnavailable(
            f"could not read the wiki's access log: {exc}"
        ) from exc
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
        "stamped_late": challenge["key"] in CHECKED_ON_A_LATER_REQUEST,
    }
