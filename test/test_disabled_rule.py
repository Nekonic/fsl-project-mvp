import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready, seen_by_both_engines

SID = 9000004
DISABLED_CASE = "board-path-traversal-static"
CONTROL_CASE = "board-sqli-search"

def _open():
    return requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600).json()["id"]

def _close(session_id):
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

def _run(cases, session_id):
    for case in cases:
        fired = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": case}, timeout=300,
        )
        assert fired.status_code == 201, fired.text
    _close(session_id)

    def control_seen_by_both(totals):
        return seen_by_both_engines(session_id, totals, name=CONTROL_CASE)

    return session_id, score_when_ready(session_id, until=control_seen_by_both)

def _verdict(score, name):
    return next(c["verdict"] for c in score["per_case"] if c["name"] == name)

@pytest.fixture(scope="module")
def disabled(stack_is_up):
    session_id = _open()
    created = requests.post(
        f"{PLATFORM_URL}/api/rules/disabled/",
        json={"sid": SID, "minutes": 10, "reason": "acceptance test", "session": session_id},
        timeout=300,
    )
    if created.status_code != 201:
        _close(session_id)
    assert created.status_code == 201, created.text
    record = dict(created.json(), session=session_id)
    try:
        record["listed"] = requests.get(
            f"{PLATFORM_URL}/api/rules/disabled/", timeout=120
        ).json()
        record["scored"] = _run([DISABLED_CASE, CONTROL_CASE], session_id)
    finally:
        _close(session_id)
        enabled = requests.post(
            f"{PLATFORM_URL}/api/rules/disabled/{record['id']}/enable/", timeout=300
        )
        assert enabled.ok, (
            f"sid {SID} could not be enabled after the test, so it stays disabled "
            f"and every later session is refused until it expires: {enabled.text}"
        )
        assert enabled.json()["enabled_at"] is not None, enabled.text
    return record

def test_the_rule_catches_the_attack_before_anything_is_disabled(full_run):
    before = full_run["score"]

    assert _verdict(before, DISABLED_CASE) == "TP", (
        "the attack was not detected even with its rule on, so this test cannot "
        "show what disabling the rule costs"
    )

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

def test_enabling_brings_the_rule_back(baseline_rules):
    session_id = _open()
    rules = f"{PLATFORM_URL}/api/rules/?session={session_id}"
    created = requests.post(
        f"{PLATFORM_URL}/api/rules/disabled/",
        json={"sid": SID, "minutes": 10, "session": session_id}, timeout=300,
    )
    assert created.status_code == 201, created.text
    disabled = requests.get(rules, timeout=60).json()["content"]
    assert not any(
        line.startswith("alert") and f"sid:{SID};" in line for line in disabled.splitlines()
    )

    enabled = requests.post(
        f"{PLATFORM_URL}/api/rules/disabled/{created.json()['id']}/enable/", timeout=300
    )
    assert enabled.ok, enabled.text

    content = requests.get(rules, timeout=60).json()["content"]
    assert content == baseline_rules
