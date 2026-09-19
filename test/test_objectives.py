"""Objectives, against the live stack.

The target judges its own defeat, so this is the one part of the score the
platform cannot be wrong about on its own. What it can get wrong is the
attribution - crediting a breach to the wrong attack, or to nobody - and that
is what these check.
"""

import subprocess
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

from conftest import PLATFORM_URL, TARGET_URL, from_attacker

# Objectives reachable with one unauthenticated request, so the test needs no
# attack chain of its own. Both pairs were verified against the live target:
# guessing the key from the name does not work, because Juice Shop's keys and
# its display names disagree - "Confidential Document" is directoryListing.
# It takes the first that nobody has taken yet.
REACHABLE = [
    ("exposedMetricsChallenge", "/metrics"),
    ("directoryListingChallenge", "/ftp/acquisitions.md"),
]


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def unsolved(stack_is_up):
    """An objective nobody has taken yet, and the path that takes it."""
    catalogue = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    solved = {o["key"] for o in catalogue if o["solved"]}

    for key, path in REACHABLE:
        if key not in solved:
            return key, path

    # Every objective this test can take has been taken, by an earlier run of
    # this very test. Reset the target rather than skipping: a skipped
    # acceptance check reads as a passed one.
    _reset_target()

    catalogue = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    solved = {o["key"] for o in catalogue if o["solved"]}
    for key, path in REACHABLE:
        if key not in solved:
            return key, path

    raise AssertionError(
        "the target was reset and still reports these objectives as solved: "
        f"{sorted(solved)}"
    )


def _reset_target():
    """Give the target back its unsolved objectives.

    A restart is not enough and neither is --force-recreate; see DECISIONS.
    Afterwards the WAF must still reach it: nginx resolves its upstream once,
    at start, so a target that comes back on a different address leaves the
    whole range answering 502 - which would surface as a defence failure.
    """
    subprocess.run(
        ["docker", "compose", "rm", "-sf", "juice-shop"],
        capture_output=True, timeout=120, check=True,
    )
    subprocess.run(
        ["docker", "compose", "up", "-d", "juice-shop"],
        capture_output=True, timeout=300, check=True,
    )

    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            if requests.get(TARGET_URL, timeout=5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(3)

    raise AssertionError(
        f"the target was reset but {TARGET_URL} does not answer through the "
        "WAF. nginx caches its upstream address at start, so recreate it too:\n"
        "  docker compose up -d --force-recreate waf suricata"
    )


@pytest.fixture(scope="module")
def breach_session(unsolved):
    """One labelled terminal window that takes one objective."""
    key, path = unsolved
    source_ip = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60).json()["source_ip"]
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=60
    ).json()["id"]

    case_id = str(uuid.uuid4())
    requests.post(f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": case_id}, timeout=30)
    try:
        started = _now()
        from_attacker(path)
        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60)
    finally:
        requests.post(f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": None}, timeout=30)

    requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": case_id, "name": "terminal-objective", "malicious": True,
            "correlation": "window", "source_ip": source_ip,
            "started_at": started.isoformat(), "ended_at": _now().isoformat(),
        },
        timeout=30,
    )
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=30)
    return session_id, key


def test_the_target_decides_an_objective_was_taken(breach_session):
    session_id, key = breach_session

    taken = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=30
    ).json()

    assert [o["key"] for o in taken] == [key]
    assert taken[0]["difficulty"] >= 1


def test_objectives_solved_before_the_session_are_not_counted(breach_session):
    # The baseline is the whole reason the target never has to be reset. If
    # this breaks, every session inherits every objective ever taken.
    session_id, _ = breach_session
    fresh = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=60).json()["id"]

    requests.post(f"{PLATFORM_URL}/api/sessions/{fresh}/objectives/", timeout=60)

    assert requests.get(
        f"{PLATFORM_URL}/api/sessions/{fresh}/objectives/", timeout=30
    ).json() == []


def test_a_breach_is_scored_and_attributed_to_the_attack_that_took_it(breach_session):
    session_id, key = breach_session
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/", timeout=180)

    scored = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60).json()

    assert scored["objectives"]["objectives"] == 1
    breach = next(b for b in scored["breaches"] if b["key"] == key)
    # Attribution, not detection, is what is asserted: whether this particular
    # request trips a rule is a property of the rule set, and the rule set is
    # the blue team's to change.
    assert breach["difficulty"] >= 1
    assert breach["detected"] is (len(breach["detection_ids"]) > 0)
    assert scored["objectives"]["coverage"] == (1.0 if breach["detected"] else 0.0)
