from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]

@pytest.fixture
def a_case(client):
    return client.get("/api/wargames/board/cases/").json()[0]

def test_the_case_catalogue_offers_attacks_and_benign_traffic(client):
    cases = client.get("/api/wargames/board/cases/").json()

    assert any(case["malicious"] for case in cases)
    assert any(not case["malicious"] for case in cases)

def test_firing_a_case_sends_it_and_records_ground_truth(client, session_id, a_case):
    with patch("api.views.harness.fire") as fired:
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]}
        )

    assert response.status_code == 201
    fired.assert_called_once()

    recorded = client.get(f"/api/sessions/{session_id}/cases/").json()
    assert [case["name"] for case in recorded] == [a_case["name"]]
    assert recorded[0]["malicious"] == a_case["malicious"]

def test_the_marker_fired_is_the_case_id_recorded(client, session_id, a_case):
    with patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]})

    fired_case = fired.call_args.args[0]
    recorded = client.get(f"/api/sessions/{session_id}/cases/").json()[0]

    assert fired_case["case_id"] == recorded["case_id"]

def test_firing_the_same_case_twice_records_two_attempts(client, session_id, a_case):
    with patch("api.views.harness.fire"):
        for _ in range(2):
            client.post_json(
                f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]}
            )

    recorded = client.get(f"/api/sessions/{session_id}/cases/").json()

    assert len(recorded) == 2
    assert recorded[0]["case_id"] != recorded[1]["case_id"]

@pytest.mark.parametrize("refusal", ["tool", "range"])
def test_an_attack_that_could_not_be_sent_is_503_with_its_reason_and_records_nothing(client, session_id, a_case, refusal):
    from range.ports import RangeUnavailable
    from redteam.harness import ToolUnavailable

    reason = "no ssh to fsl-kali: Host key verification failed."
    raised = ToolUnavailable(reason) if refusal == "tool" else RangeUnavailable(reason)
    with patch("api.views.harness.fire", side_effect=raised):
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]}
        )

    assert response.status_code == 503
    assert "Host key verification failed" in response.json()["detail"], (
        "the reason the range gave was thrown away and the operator got "
        "Django's generic Server Error page"
    )
    assert client.get(f"/api/sessions/{session_id}/cases/").json() == [], (
        "a case recorded for an attack that never left would be scored as a miss"
    )
