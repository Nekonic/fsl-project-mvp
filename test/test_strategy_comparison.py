import uuid
from datetime import datetime, timezone

import pytest
import requests

from conftest import PLATFORM_URL, from_attacker, score_when_ready

ATTACK_PATH = "/rest/products/search?q=%27%20OR%201%3D1--"

def _now():
    return datetime.now(timezone.utc)

def _label(case_id):
    response = requests.post(
        f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": case_id}, timeout=30
    )
    assert response.ok, response.text

@pytest.fixture(scope="module")
def labelled_session(stack_is_up):
    source_ip = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60).json()["source_ip"]
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=30
    ).json()["id"]

    case_id = str(uuid.uuid4())
    _label(case_id)
    try:
        started = _now()
        from_attacker(ATTACK_PATH)
        ended = _now()
    finally:
        _label(None)

    recorded = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": case_id,
            "name": "terminal-both-ways",
            "malicious": True,
            "correlation": "window",
            "source_ip": source_ip,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
        },
        timeout=30,
    )
    assert recorded.status_code == 201, recorded.text

    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=30)
    return session_id

def _scored(session_id, strategy):
    response = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/score/",
        params={"correlation": strategy},
        timeout=60,
    )
    assert response.ok, response.text
    return response.json()

@pytest.fixture(scope="module")
def ready(labelled_session):
    score_when_ready(labelled_session, until=lambda totals: totals["tp"] > 0)
    return labelled_session

def test_the_proxy_marked_free_form_traffic(ready):
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{ready}/detections/", timeout=30
    ).json()

    assert any(detection["marker"] for detection in detections), (
        "no alert carried a marker, so the proxy did not stamp the window"
    )

def test_both_strategies_find_the_same_attack(ready):
    by_marker = _scored(ready, "marker")
    by_window = _scored(ready, "window")

    assert by_marker["tp"] == 1, "the marker path missed a window it had stamped"
    assert by_window["tp"] == 1, "the window path missed traffic from its own source"

def test_the_two_strategies_are_reported_separately(ready):
                                                                            
                                                                           
             
    by_marker = _scored(ready, "marker")
    by_window = _scored(ready, "window")

    assert by_marker["per_case"][0]["detection_ids"]
    assert by_window["per_case"][0]["detection_ids"]
