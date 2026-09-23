from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]

@pytest.fixture
def a_case(client):
    return client.get("/api/wargames/juice-shop/cases/").json()[0]

def test_wargames_lists_the_only_target(client):
    response = client.get("/api/wargames/")

    assert response.status_code == 200
    assert [w["id"] for w in response.json()] == ["juice-shop"]
    assert response.json()[0]["cases"] > 0

def test_case_catalogue_describes_what_each_button_fires(client):
    cases = client.get("/api/wargames/juice-shop/cases/").json()

    assert len(cases) > 1
    assert any(case["malicious"] for case in cases)
                                                                            
                                                     
    assert any(not case["malicious"] for case in cases)
    for case in cases:
        assert case["name"]
        assert case["summary"]

def test_case_catalogue_for_an_unknown_wargame_is_404(client):
    assert client.get("/api/wargames/nothing/cases/").status_code == 404

def test_sessions_can_be_listed_newest_first(client):
    first = client.post_json("/api/sessions/", {}).json()["id"]
    second = client.post_json("/api/sessions/", {}).json()["id"]

    listed = client.get("/api/sessions/").json()

    assert [s["id"] for s in listed][:2] == [second, first]

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

    fired_case = fired.call_args.args[1]
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

def test_firing_an_unknown_case_is_404_and_records_nothing(client, session_id):
    with patch("api.views.harness.fire") as fired:
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": "no-such-case"}
        )

    assert response.status_code == 404
    fired.assert_not_called()
    assert client.get(f"/api/sessions/{session_id}/cases/").json() == []

def test_firing_into_an_unknown_session_is_404(client, a_case):
    with patch("api.views.harness.fire") as fired:
        response = client.post_json("/api/sessions/9999/attacks/", {"case": a_case["name"]})

    assert response.status_code == 404
    fired.assert_not_called()

def test_a_tool_that_will_not_run_is_reported_not_swallowed(client, session_id, a_case):
    from redteam.harness import ToolUnavailable

    with patch("api.views.harness.fire", side_effect=ToolUnavailable("no image")):
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]}
        )

    assert response.status_code == 503
    assert "no image" in response.json()["detail"]
                                                            
    assert client.get(f"/api/sessions/{session_id}/cases/").json() == []

def test_a_range_that_cannot_start_the_tool_is_503_with_its_reason(client, session_id, a_case):
    from range.ports import RangeUnavailable

    with patch(
        "api.views.harness.fire",
        side_effect=RangeUnavailable("no ssh to fsl-kali: Host key verification failed."),
    ):
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": a_case["name"]}
        )

    assert response.status_code == 503
    assert "Host key verification failed" in response.json()["detail"], (
        "the reason the range gave was thrown away and the operator got "
        "Django's generic Server Error page"
    )
    assert client.get(f"/api/sessions/{session_id}/cases/").json() == []
