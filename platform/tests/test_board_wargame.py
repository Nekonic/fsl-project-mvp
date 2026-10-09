from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

TRUTH = {"admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
         "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO="}

def board_session(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]

def listed(client):
    return {w["id"]: w for w in client.get("/api/wargames/").json()}

def test_the_board_is_a_second_wargame_on_its_own_host(client):
    wargames = listed(client)

    assert wargames["board"]["public_url"] == "http://board.com"

def test_the_catalogue_lists_the_board_and_the_corp_site_both_judged(client):
    wargames = listed(client)

    assert set(wargames) == {"board", "corp"}
    assert wargames["board"]["judged"] is True
    assert wargames["corp"]["judged"] is True

def test_the_board_ships_attacks_and_benign_traffic(client):
    cases = client.get("/api/wargames/board/cases/").json()

    assert any(case["malicious"] for case in cases)
    assert any(not case["malicious"] for case in cases)

def test_the_board_lists_its_loot_tiers(client):
    response = client.get("/api/wargames/board/objectives/")

    assert {o["key"] for o in response.json()} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }

def test_a_board_session_observes_nothing_and_close_confesses_nothing(client):
    session_id = board_session(client)
    observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    closed = client.post_json(f"/api/sessions/{session_id}/close/")

    assert observed.json() == {"achieved": 0, "total": 0}
    assert "unobserved" not in closed.json()

def test_a_board_session_opens_with_the_ground_truth_snapshot(client):
    session_id = board_session(client)

    assert Session.objects.get(pk=session_id).baseline == TRUTH

def test_a_board_case_is_addressed_to_the_board(client):
    session_id = board_session(client)
    name = client.get("/api/wargames/board/cases/").json()[0]["name"]

    with patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": name})

    assert fired.call_args.args[0]["request"]["headers"]["Host"] == "board.com"

def test_a_session_with_no_scenario_fires_cases_at_the_board(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    name = next(
        c["name"] for c in client.get("/api/wargames/board/cases/").json()
        if c["summary"].split()[0] in {"GET", "POST"}
    )

    with patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": name})

    assert fired.call_args.args[0]["request"]["headers"]["Host"] == "board.com"
