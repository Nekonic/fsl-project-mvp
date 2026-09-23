import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

BUFFERLESS = (
    'alert http any any -> any any (msg:"FSL UNION without a buffer"; '
    'flow:established,to_server; content:"UNION"; nocase; sid:9009996; rev:1;)\n'
)
CASE = "sqli-union-user-table"


def signatures(session_id):
    listed = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120).json()
    return {d["detection_id"]: d["signature"] for d in listed}


@pytest.fixture(scope="module")
def caught_by_a_rule_without_a_buffer(stack_is_up, baseline_rules):
    applied = requests.post(f"{PLATFORM_URL}/api/rules/apply/", json={"content": BUFFERLESS}, timeout=180)
    assert applied.ok, applied.text
    session_id = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120).json()["id"]
    try:
        fired = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/", json={"case": CASE}, timeout=300,
        )
        assert fired.status_code == 201, fired.text
        case_id = fired.json()["case_id"]

        def credited(totals):
            owned = next((c for c in totals["per_case"] if c["case_id"] == case_id), {})
            sigs = signatures(session_id)
            return any(sigs.get(d, "").startswith("FSL UNION without a buffer") for d in owned.get("detection_ids", []))

        totals = score_when_ready(session_id, until=credited)
        yield totals, case_id, signatures(session_id)
    finally:
        requests.post(f"{PLATFORM_URL}/api/rules/apply/", json={"content": baseline_rules}, timeout=180)


def test_a_rule_without_an_app_layer_buffer_still_credits_the_case_it_caught(caught_by_a_rule_without_a_buffer):
    totals, case_id, sigs = caught_by_a_rule_without_a_buffer
    owned = next(c for c in totals["per_case"] if c["case_id"] == case_id)
    fired = [d for d, s in sigs.items() if s.startswith("FSL UNION without a buffer")]

    assert fired, "the buffer-less rule never fired, so this proves nothing about the join"
    assert set(fired) & set(owned["detection_ids"]), (
        f"the rule fired {len(fired)} times on the case's own request, but an alert "
        f"from a signature with no app-layer keyword carries no tx_id, so it met no "
        f"http event, got no marker, and the case it caught did not own it"
    )
