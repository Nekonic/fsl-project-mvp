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
