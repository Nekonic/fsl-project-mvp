from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings

import wargames

TIMEOUT = 15
READ_INSIDE = ("import sys, urllib.request; "
               "sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=float(sys.argv[2])).read().decode())")


class GroundTruthUnavailable(RuntimeError):
    pass


def ground_truth(wargame_id: str, host: str = "", inside=None) -> dict[str, str]:
    spec = wargames.objectives(wargame_id)
    if inside is not None:
        return _from_inside(spec, inside)
    url = _board_url(host).rstrip("/") + spec["secret"]["read_path"]
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GroundTruthUnavailable(f"could not read ground truth from {url}: {exc}") from exc
    return _mapped(body, url)


def _from_inside(spec: dict, inside) -> dict[str, str]:
    port = urllib.parse.urlsplit(settings.BOARD_API_URL).port or 80
    url = f"http://127.0.0.1:{port}{spec['secret']['read_path']}"
    try:
        ran = inside(["python", "-c", READ_INSIDE, url, str(TIMEOUT)], timeout=TIMEOUT + 30)
    except RuntimeError as exc:
        raise GroundTruthUnavailable(f"could not reach the board to read {url}: {exc}") from exc
    if not ran.ok:
        raise GroundTruthUnavailable(f"the board could not read {url} (exit {ran.exit_code}): {ran.output[-300:]}")
    try:
        body = json.loads(ran.output)
    except ValueError as exc:
        raise GroundTruthUnavailable(f"{url} inside the board answered no JSON: {exc}") from exc
    return _mapped(body, url)


def _mapped(body, url: str) -> dict[str, str]:
    if not isinstance(body, dict):
        raise GroundTruthUnavailable(f"{url} did not return a username to hash map")
    return {str(name): str(digest) for name, digest in body.items()}


def _board_url(host: str) -> str:
    declared = urllib.parse.urlsplit(settings.BOARD_API_URL)
    if not host:
        return declared.geturl()
    return declared._replace(
        netloc=f"{host}:{declared.port}" if declared.port else host
    ).geturl()


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
