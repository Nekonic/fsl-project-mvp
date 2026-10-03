from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}


def _start_board(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def test_a_board_session_snapshots_the_ground_truth_at_start(client):
    session_id = _start_board(client)

    assert Session.objects.get(pk=session_id).baseline == TRUTH, (
        "a loot_verified session must snapshot username->hash onto baseline at "
        "start so a close-time rebuild cannot wipe the comparison set"
    )


def test_a_board_session_opens_blind_when_the_channel_is_down(client):
    from api import loot

    with patch("api.views.loot.ground_truth",
               side_effect=loot.GroundTruthUnavailable("board down")):
        session_id = client.post_json(
            "/api/sessions/", {"scenario": "board"}
        ).json()["id"]

    assert Session.objects.get(pk=session_id).baseline is None


def test_the_board_lists_its_tier_ladder_and_never_asks_juice_shop(client):
    with patch("objectives._fetch") as fetched:
        response = client.get("/api/wargames/board/objectives/")

    assert {o["key"] for o in response.json()} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    fetched.assert_not_called()


def test_observing_a_board_session_does_not_self_judge(client):
    session_id = _start_board(client)

    with patch("objectives._fetch") as fetched, patch(
        "api.views.objectives.observe"
    ) as observed:
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.json() == {"achieved": 0, "total": 0}
    fetched.assert_not_called()
    observed.assert_not_called()
