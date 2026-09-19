"""Window correlation, against the live stack.

`correlation: window` has been implemented and unit-tested to its boundaries
since v1.0 and had never once run against the real pipeline - the known gap in
docs/STATE.md. Every case in `redteam/cases/` carries the marker header, so
nothing exercised the path that matches on source IP and time instead.

The labelled terminal in the red team console is that path, and a person can
now take it, so it needs an acceptance test of its own.
"""

import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

from conftest import PLATFORM_URL, from_attacker, score_when_ready

# Windows are matched with two seconds of slack at each end, so consecutive
# windows must be further apart than that, or one window's traffic is
# attributed to the next one's case as well.
GAP_SECONDS = 6

ATTACK_PATH = "/rest/products/search?q=%27%20OR%201%3D1--"
BENIGN_PATH = "/rest/products/search?q=apple"


def _now():
    return datetime.now(timezone.utc)


def _record_window(session_id, name, malicious, source_ip, started_at, ended_at):
    response = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": str(uuid.uuid4()),
            "name": name,
            "malicious": malicious,
            "correlation": "window",
            "source_ip": source_ip,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        timeout=30,
    )
    assert response.status_code == 201, response.text


@pytest.fixture(scope="module")
def window_session(stack_is_up):
    """Two labelled terminal windows: one attack, one benign, kept apart."""
    attacker = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60)
    assert attacker.ok, (
        f"the attacker box is not available: {attacker.text}. "
        f"Run `docker compose up -d kali`."
    )
    source_ip = attacker.json()["source_ip"]

    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=30
    ).json()["id"]

    started = _now()
    from_attacker(ATTACK_PATH)
    _record_window(session_id, "terminal-sqli", True, source_ip, started, _now())

    time.sleep(GAP_SECONDS)

    started = _now()
    from_attacker(BENIGN_PATH)
    _record_window(session_id, "terminal-benign", False, source_ip, started, _now())

    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=30)
    return session_id


@pytest.fixture(scope="module")
def window_score(window_session):
    def ready(totals):
        verdicts = {case["name"]: case["verdict"] for case in totals["per_case"]}
        return verdicts.get("terminal-sqli") == "TP"

    return score_when_ready(window_session, until=ready)


def test_an_unlabelled_attack_is_scored_by_time_and_source(window_score):
    verdicts = {case["name"]: case["verdict"] for case in window_score["per_case"]}

    assert verdicts["terminal-sqli"] == "TP"


def test_benign_terminal_traffic_in_its_own_window_stays_clean(window_score):
    # Without this the strategy could "work" by attributing every alert in the
    # session to every window, which would make false positives unscorable.
    verdicts = {case["name"]: case["verdict"] for case in window_score["per_case"]}

    assert verdicts["terminal-benign"] == "TN"


def test_the_match_was_made_without_a_marker(window_session, window_score):
    """Proof that this is the window path and not the marker path.

    Terminal traffic carries no X-FSL-Case header at all, so if these alerts
    had markers the test would be passing for the wrong reason.
    """
    matched = {
        detection_id
        for case in window_score["per_case"]
        if case["name"] == "terminal-sqli"
        for detection_id in case["detection_ids"]
    }
    assert matched, "nothing was attributed to the attack window"

    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{window_session}/detections/", timeout=30
    ).json()

    markers = {
        detection["marker"]
        for detection in detections
        if detection["id"] in matched or detection["detection_id"] in matched
    }
    assert markers <= {None}, f"expected unlabelled traffic, saw markers {markers}"
