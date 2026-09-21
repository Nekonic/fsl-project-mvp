"""The only file that knows how each target says it was beaten.

A target judges its own defeat. Every challenge the shop ships is an objective
with a name, a category and a difficulty, and it flips `solved` itself - so
whether an attack achieved anything is ground truth we do not have to label,
produce or be trusted on.

The internal wiki judges itself the same way, by its own access log. It is a
second target because an estate with one host in it has no inside: there is
nowhere to move to, so everything after initial access is missing. Reaching it
means making the application fetch it, which is the attack the trade describes
as using the web app as a proxy into the estate.

Polled directly, never through the WAF: a poll every few seconds through the
proxy would appear in the alert stream as traffic the range generated about
itself, and could be scored as a false positive against the defence.
"""

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


# The one objective that is not the shop's. Difficulty is the shop's own scale,
# where 6 is its SSRF challenge - which is the step this needs.
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
    """Every objective the targets offer, whether or not anyone reached them."""
    return [_summarise(challenge) for challenge in _fetch()] + [_internal()]


def solved_keys() -> set[str]:
    taken = {c["key"] for c in _fetch() if c.get("solved")}
    if _internal()["solved"]:
        taken.add(INTERNAL["key"])
    return taken


def _internal() -> dict[str, Any]:
    """What the wiki says was read of it.

    Its own record, not ours: nothing here infers the deed from the traffic.
    A read at all is the objective - the wiki cannot know who asked for it,
    and nothing else in the estate has a reason to.
    """
    when = None
    try:
        for line in Path(settings.WIKI_READ_LOG).read_text().splitlines():
            stamp, _, rest = line.partition(" ")
            if settings.WIKI_SECRET_PATH in rest:
                when = stamp
    except OSError:
        # No log is not "not taken" - it is a wiki that has never been asked
        # for anything, which is the same answer for our purposes.
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
        # When the target says it was beaten. Worth more than the moment we
        # noticed: `solved` flips after the request that did it has already
        # been answered, so any poll is late by an unknown amount, and
        # attribution is by time. Not trusted blindly - see the caller.
        "solved_at": challenge.get("updatedAt") or None,
    }
