from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

import wargames

TIMEOUT = 15


class GroundTruthUnavailable(RuntimeError):
    pass


def ground_truth(wargame_id: str) -> dict[str, str]:
    spec = wargames.objectives(wargame_id)
    url = settings.BOARD_API_URL.rstrip("/") + spec["secret"]["read_path"]
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GroundTruthUnavailable(f"could not read ground truth from {url}: {exc}") from exc
    if not isinstance(body, dict):
        raise GroundTruthUnavailable(f"{url} did not return a username to hash map")
    return {str(name): str(digest) for name, digest in body.items()}


def canonicalize(submitted: Any) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    if isinstance(submitted, dict):
        rows = list(submitted.items())
    elif isinstance(submitted, list):
        rows = submitted
    else:
        return pairs
    for row in rows:
        username, digest = _row(row)
        if isinstance(username, str) and isinstance(digest, str):
            pairs.add((username, digest))
    return pairs


def _row(row: Any):
    if isinstance(row, dict):
        return row.get("username"), row.get("hash", row.get("password"))
    if isinstance(row, (list, tuple)) and len(row) == 2:
        return row[0], row[1]
    return None, None


def matched(submitted: Any, truth: dict[str, str]) -> set[str]:
    return {name for name, digest in canonicalize(submitted) if truth.get(name) == digest}


def tiers_fired(spec: dict, matched_usernames: set[str], truth: dict[str, str]):
    coverage = len(matched_usernames) / len(truth) if truth else 0.0
    fired = [tier for tier in spec["tiers"] if _fires(tier, matched_usernames, coverage)]
    return fired, coverage


def _fires(tier: dict, matched_usernames: set[str], coverage: float) -> bool:
    if "min_matched" in tier:
        return len(matched_usernames) >= tier["min_matched"]
    if "account" in tier:
        return tier["account"] in matched_usernames
    if "coverage" in tier:
        return coverage >= tier["coverage"]
    return False
