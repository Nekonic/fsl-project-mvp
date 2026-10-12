import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready, seen_by_both_engines

SID = 9000004
SILENCED_CASE = "board-path-traversal-static"
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
def silenced(stack_is_up):
    session_id = _open()
    created = requests.post(
        f"{PLATFORM_URL}/api/rules/suppressions/",
        json={"sid": SID, "minutes": 10, "reason": "acceptance test", "session": session_id},
        timeout=300,
    )
    if created.status_code != 201:
        _close(session_id)
    assert created.status_code == 201, created.text
    record = dict(created.json(), session=session_id)
    try:
        record["listed"] = requests.get(
            f"{PLATFORM_URL}/api/rules/suppressions/", timeout=120
        ).json()
        record["scored"] = _run([SILENCED_CASE, CONTROL_CASE], session_id)
    finally:
        _close(session_id)
        restored = requests.post(
            f"{PLATFORM_URL}/api/rules/suppressions/{record['id']}/restore/", timeout=300
        )
        assert restored.ok, (
            f"sid {SID} could not be restored after the test, so it stays silenced "
            f"and every later session is refused until it expires: {restored.text}"
        )
        assert restored.json()["restored_at"] is not None, restored.text
    return record

def test_the_rule_catches_the_attack_before_anything_is_silenced(full_run):
    before = full_run["score"]

    assert _verdict(before, SILENCED_CASE) == "TP", (
        "the attack was not detected even with its rule on, so this test cannot "
        "show what silencing the rule costs"
    )

def test_silencing_the_rule_turns_the_attack_into_a_miss(silenced):
    session_id, after = silenced["scored"]

    assert seen_by_both_engines(session_id, after, name=CONTROL_CASE), (
        f"{CONTROL_CASE} was fired after {SILENCED_CASE} and never reached the "
        f"score from both engines, so an alert for the silenced case may simply "
        f"not have landed yet and a miss here proves nothing"
    )
    assert _verdict(after, SILENCED_CASE) == "FN", (
        "the rule was silenced and the attack was still detected - either the "
        "reload did not happen or something else catches it"
    )
    assert _verdict(after, CONTROL_CASE) == "TP"

def test_a_silenced_rule_is_on_the_books_with_a_deadline(silenced):
    listed = silenced["listed"]

    live = [s for s in listed["suppressions"] if s["sid"] == SID]
    assert live, "a silenced rule that nothing records is a rule silenced for good"
    assert live[0]["expires_at"] > live[0]["created_at"]

def test_restoring_brings_the_rule_back(baseline_rules):
    session_id = _open()
    rules = f"{PLATFORM_URL}/api/rules/?session={session_id}"
    created = requests.post(
        f"{PLATFORM_URL}/api/rules/suppressions/",
        json={"sid": SID, "minutes": 10, "session": session_id}, timeout=300,
    )
    assert created.status_code == 201, created.text
    silenced = requests.get(rules, timeout=60).json()["content"]
    assert not any(
        line.startswith("alert") and f"sid:{SID};" in line for line in silenced.splitlines()
    )

    restored = requests.post(
        f"{PLATFORM_URL}/api/rules/suppressions/{created.json()['id']}/restore/", timeout=300
    )
    assert restored.ok, restored.text

    content = requests.get(rules, timeout=60).json()["content"]
    assert content == baseline_rules
