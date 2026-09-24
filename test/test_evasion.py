import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

PLUS = "sqli-or-1-1-plus-encoded"
PERCENT = "sqli-login-bypass"

@pytest.fixture(scope="module")
def fired(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    for case in (PERCENT, PLUS):
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": case}, timeout=300,
        )
        assert sent.status_code == 201, sent.text
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    def control_seen_by_both(totals):
        control = next(
            (c for c in totals["per_case"] if c["name"] == PERCENT), None
        )
        if not control or not control["detected"]:
            return False
        by_id = {
            d["detection_id"]: d for d in requests.get(
                f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
            ).json()
        }
        sources = {
            by_id[d]["source"] for d in control["detection_ids"] if d in by_id
        }
        return {"suricata", "modsecurity"} <= sources

    score = score_when_ready(session_id, until=control_seen_by_both)
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    return score, {d["detection_id"]: d for d in detections}

def _case(fired, name):
    score, _ = fired
    return next(c for c in score["per_case"] if c["name"] == name)

def _engines(fired, name):
    _, by_id = fired
    return {
        by_id[d]["source"] for d in _case(fired, name)["detection_ids"] if d in by_id
    }

def test_both_encodings_are_detected_by_the_stack(fired):
    assert _case(fired, PERCENT)["verdict"] == "TP"
    assert _case(fired, PLUS)["verdict"] == "TP"

def test_the_control_is_caught_by_both_engines(fired):
    assert {"suricata", "modsecurity"} <= _engines(fired, PERCENT)

def test_the_ids_catches_the_plus_encoding_too(fired):
    assert "suricata" in _engines(fired, PLUS), (
        f"only {sorted(_engines(fired, PLUS))} caught the plus-encoded "
        f"injection - the IDS rules match an encoding rather than an attack, "
        f"and the WAF is covering for them"
    )
