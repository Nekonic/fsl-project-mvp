from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

STATE = {
    "admins": [1],
    "options": {"users_can_register": "0", "default_role": "subscriber"},
    "posts": [2, 3],
}


def _start_corp(client):
    with patch("api.views.effect.snapshot", return_value=dict(STATE)):
        return client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]


def test_a_corp_session_snapshots_the_target_state_at_start(client):
    session_id = _start_corp(client)
    assert Session.objects.get(pk=session_id).baseline == STATE


def test_a_corp_session_opens_blind_when_the_state_read_fails(client):
    from api import effect
    with patch("api.views.effect.snapshot",
               side_effect=effect.StateUnavailable("corp down")):
        session_id = client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]
    assert Session.objects.get(pk=session_id).baseline is None


def test_corp_lists_its_three_objectives_unsolved(client):
    by_key = {o["key"]: o for o in client.get("/api/wargames/corp/objectives/").json()}
    assert set(by_key) == {"corp-rogue-admin", "corp-self-registration", "corp-content-overwrite"}
    for tier in by_key.values():
        assert isinstance(tier["difficulty"], int)
        assert tier["solved"] is False and tier["solved_at"] is None
