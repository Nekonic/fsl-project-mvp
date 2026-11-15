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
