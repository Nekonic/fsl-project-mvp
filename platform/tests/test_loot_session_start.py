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


def test_the_board_lists_its_tier_ladder_with_every_field_unsolved(client):
    response = client.get("/api/wargames/board/objectives/")

    tiers = {o["key"]: o for o in response.json()}
    assert set(tiers) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    for tier in tiers.values():
        assert tier["name"] and tier["category"]
        assert isinstance(tier["difficulty"], int)
        assert tier["solved"] is False
        assert tier["solved_at"] is None


def test_observing_a_board_session_records_nothing(client):
    session_id = _start_board(client)

    response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.json() == {"achieved": 0, "total": 0}
