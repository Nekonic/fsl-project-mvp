"""The only file that knows Juice Shop's challenge API.

The target judges its own defeat. Every challenge it ships is an objective with
a name, a category and a difficulty, and it flips `solved` itself - so whether
an attack achieved anything is ground truth we do not have to label, produce or
be trusted on.

Polled directly, never through the WAF: a poll every few seconds through the
proxy would appear in the alert stream as traffic the range generated about
itself, and could be scored as a false positive against the defence.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

_TIMEOUT = 15


class ObjectivesUnavailable(RuntimeError):
    """The target is not answering, so nothing can be said about objectives."""


def catalogue() -> list[dict[str, Any]]:
    """Every objective the target offers, whether or not anyone has reached it."""
    return [_summarise(challenge) for challenge in _fetch()]


def solved_keys() -> set[str]:
    return {c["key"] for c in _fetch() if c.get("solved")}


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
        # When the target says it was beaten. Worth more than the moment we
        # noticed: `solved` flips after the request that did it has already
        # been answered, so any poll is late by an unknown amount, and
        # attribution is by time. Not trusted blindly - see the caller.
        "solved_at": challenge.get("updatedAt") or None,
    }
