from unittest.mock import patch

import pytest

from api import loot
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


@pytest.mark.parametrize("unread", [
    {"side_effect": loot.GroundTruthUnavailable("board down")},
    {"return_value": {}},
])
def test_a_board_session_whose_accounts_cannot_be_read_is_refused_and_closed(client, unread):
    with patch("api.views.loot.ground_truth", **unread):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 503, answer.content
    assert "accounts could not be read" in answer.json()["detail"]
    assert Session.objects.get().ended_at is not None, (
        "a board session with no snapshot cannot tell a leak from a block"
    )


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
