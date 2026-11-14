import pytest
import requests

from conftest import PLATFORM_URL, runs_the_declared_rules, score_when_ready, seen_by_both_engines

SID = 9000004
DISABLED_CASE = "board-path-traversal-static"
CONTROL_CASE = "board-sqli-search"

def _open():
    return requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600).json()["id"]

def _close(session_id):
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

def _rules(session_id):
    return requests.get(f"{PLATFORM_URL}/api/rules/?session={session_id}", timeout=60).json()["content"]

def _fire(cases, session_id):
    for case in cases:
        fired = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": case}, timeout=300,
        )
        assert fired.status_code == 201, fired.text

def _control_seen_by_both(session_id):
    return lambda totals: seen_by_both_engines(session_id, totals, name=CONTROL_CASE)

def _verdict(score, name):
    return next(c["verdict"] for c in score["per_case"] if c["name"] == name)

def _enable(record):
    enabled = requests.post(
        f"{PLATFORM_URL}/api/rules/disabled/{record['id']}/enable/", timeout=300
    )
    assert enabled.ok, (
        f"sid {SID} could not be enabled after the test, so it stays disabled "
        f"and every later session is refused until it expires: {enabled.text}"
    )
    assert enabled.json()["enabled_at"] is not None, enabled.text
    return enabled

@pytest.fixture(scope="module")
def disabled(stack_is_up):
    session_id = _open()
    try:
        baseline = runs_the_declared_rules(session_id)
    except AssertionError:
        _close(session_id)
        raise
    created = requests.post(
        f"{PLATFORM_URL}/api/rules/disabled/",
        json={"sid": SID, "minutes": 10, "reason": "acceptance test", "session": session_id},
        timeout=300,
    )
    if created.status_code != 201:
        _close(session_id)
    assert created.status_code == 201, created.text
    record = dict(created.json(), session=session_id, baseline=baseline)
    try:
        record["listed"] = requests.get(
            f"{PLATFORM_URL}/api/rules/disabled/", timeout=120
        ).json()
        record["rules_while_disabled"] = _rules(session_id)
        _fire([DISABLED_CASE, CONTROL_CASE], session_id)
        score_when_ready(session_id, until=_control_seen_by_both(session_id))
        record["enabled"] = _enable(record)
        record["rules_after_enabling"] = _rules(session_id)
    finally:
        _close(session_id)
        if "enabled" not in record:
            _enable(record)
    record["scored"] = (session_id, score_when_ready(session_id, until=_control_seen_by_both(session_id)))
    return record

def test_disabling_the_rule_turns_the_attack_into_a_miss(disabled):
    session_id, after = disabled["scored"]

    assert seen_by_both_engines(session_id, after, name=CONTROL_CASE), (
        f"{CONTROL_CASE} was fired after {DISABLED_CASE} and never reached the "
        f"score from both engines, so an alert for the disabled case may simply "
        f"not have landed yet and a miss here proves nothing"
    )
    assert _verdict(after, DISABLED_CASE) == "FN", (
        "the rule was disabled and the attack was still detected - either the "
        "reload did not happen or something else catches it"
    )
    assert _verdict(after, CONTROL_CASE) == "TP"

def test_a_disabled_rule_is_on_the_books_with_a_deadline(disabled):
    listed = disabled["listed"]

    live = [s for s in listed["disabled"] if s["sid"] == SID]
    assert live, "a disabled rule that nothing records is a rule disabled for good"
    assert live[0]["expires_at"] > live[0]["created_at"]

def test_enabling_brings_the_rule_back(disabled):
    assert not any(
        line.startswith("alert") and f"sid:{SID};" in line
        for line in disabled["rules_while_disabled"].splitlines()
    )

    assert disabled["enabled"].ok, disabled["enabled"].text
    assert disabled["rules_after_enabling"] == disabled["baseline"]
