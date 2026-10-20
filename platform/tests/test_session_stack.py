from unittest.mock import patch

import pytest

from api.models import Session
from range.ports import RangeUnavailable

pytestmark = pytest.mark.django_db


class Recording:
    def __init__(self, order, fails=False):
        self.order = order
        self.fails = fails

    def runner(self, role):
        if self.fails:
            raise RangeUnavailable("fsl-edge did not answer")
        return lambda *args, **kwargs: None


def test_the_baseline_is_the_board_s_accounts_read_at_open(client):
    order = []

    def ground_truth(wargame_id, host=""):
        order.append(("baseline", wargame_id))
        return [{"username": "admin", "password": "x"}]

    with patch("api.views.substrate", lambda: Recording(order)), \
            patch("api.views.loot.ground_truth", ground_truth):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 201, answer.content
    session_id = answer.json()["id"]
    assert order == [("baseline", "board")]
    assert Session.objects.get(pk=session_id).baseline == [
        {"username": "admin", "password": "x"}
    ]


@pytest.mark.takes_defense
def test_an_open_the_range_cannot_finish_leaves_no_open_session(client):
    order = []

    with patch("api.views.substrate", lambda: Recording(order, fails=True)):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 503, answer.content
    assert not Session.objects.filter(ended_at=None).exists(), (
        "a session whose target never came up stays open and is scored "
        "against nothing"
    )


def test_a_baseline_read_that_fails_after_the_row_exists_closes_it(client):
    def ground_truth(wargame_id, host=""):
        raise ValueError("board answered with something that is not JSON")

    with patch("api.views.substrate", lambda: Recording([])), \
            patch("api.views.loot.ground_truth", ground_truth), \
            pytest.raises(ValueError):
        client.post_json("/api/sessions/", {"scenario": "board"})

    assert Session.objects.exists()
    assert not Session.objects.filter(ended_at=None).exists(), (
        "a session whose baseline was never read stays open and blocks the "
        "next one with 409"
    )


def test_the_baseline_is_read_from_the_board_the_substrate_reports(client):
    asked = []

    class Addressed(Recording):
        def address(self, role):
            asked.append(role)
            return "10.20.0.7"

    def ground_truth(wargame_id, host=""):
        asked.append(host)
        return [{"username": "admin", "password": "x"}]

    with patch("api.views.substrate", lambda: Addressed([])), \
            patch("api.views.loot.ground_truth", ground_truth):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 201, answer.content
    assert asked == ["board", "10.20.0.7"], (
        "the baseline came from the board named in settings, not the board "
        "VM the red team attacks"
    )

