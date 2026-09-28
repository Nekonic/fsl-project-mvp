from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

def board_session(client):
    return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]

def listed(client):
    return {w["id"]: w for w in client.get("/api/wargames/").json()}

def test_the_board_is_a_second_wargame_on_its_own_host(client):
    wargames = listed(client)

    assert wargames["board"]["public_url"] == "http://board.com"
    assert wargames["juice-shop"]["public_url"] == "http://shop.com"

def test_only_juice_shop_judges_its_own_defeat(client):
    wargames = listed(client)

    assert wargames["juice-shop"]["judged"] is True
    assert wargames["board"]["judged"] is False

def test_the_board_ships_attacks_and_benign_traffic(client):
    cases = client.get("/api/wargames/board/cases/").json()

    assert any(case["malicious"] for case in cases)
    assert any(not case["malicious"] for case in cases)

def test_the_board_lists_no_objectives_and_never_asks_juice_shop(client):
    with patch("objectives._fetch") as fetched:
        response = client.get("/api/wargames/board/objectives/")

    assert response.json() == []
    fetched.assert_not_called()

def test_a_board_session_never_asks_juice_shop_what_fell(client):
    with patch("objectives._fetch") as fetched:
        session_id = board_session(client)
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
        closed = client.post_json(f"/api/sessions/{session_id}/close/")

    assert observed.json() == {"achieved": 0, "total": 0}
    assert "unobserved" not in closed.json()
    fetched.assert_not_called()

def test_a_board_session_opens_with_nothing_already_taken(client):
    with patch("objectives._fetch") as fetched:
        session_id = board_session(client)

    assert Session.objects.get(pk=session_id).baseline == []
    fetched.assert_not_called()

def test_a_board_case_is_addressed_to_the_board(client):
    session_id = board_session(client)
    name = client.get("/api/wargames/board/cases/").json()[0]["name"]

    with patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": name})

    assert fired.call_args.args[1]["request"]["headers"]["Host"] == "board.com"

def test_a_juice_shop_case_is_still_addressed_to_the_shop(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    name = next(
        c["name"] for c in client.get("/api/wargames/juice-shop/cases/").json()
        if c["summary"].split()[0] in {"GET", "POST"}
    )

    with patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": name})

    assert fired.call_args.args[1]["request"]["headers"]["Host"] == "shop.com"
