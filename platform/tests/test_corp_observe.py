from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api import effect
from api.models import Objective, Session

pytestmark = pytest.mark.django_db

BASELINE = {
    "admins": [1],
    "options": {"users_can_register": "0", "default_role": "subscriber"},
    "posts": [2],
}


def _start(client):
    with patch("api.views.effect.snapshot", return_value=dict(BASELINE)):
        return client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]


def _fire(client, session_id, name):
    now = datetime.now(timezone.utc)
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": f"c-{name}", "name": name, "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })
    return now


def _rogue_admin_change(at):
    return effect.Change(
        table="wp_usermeta", kind="insert", at=at,
        columns={2: "7", 3: "wp_capabilities", 4: 'a:1:{s:13:"administrator";b:1;}'},
    )


def test_a_rogue_admin_change_in_a_malicious_window_credits_the_objective(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)

    with patch("api.views.effect.read_changes", return_value=[_rogue_admin_change(at)]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert observed.json()["achieved"] == 1
    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {"corp-rogue-admin"}


def test_a_change_that_matches_the_baseline_credits_nothing(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)
    same_admin = effect.Change(
        table="wp_usermeta", kind="update", at=at,
        columns={2: "1", 3: "wp_capabilities", 4: 'a:1:{s:13:"administrator";b:1;}'},
    )
    with patch("api.views.effect.read_changes", return_value=[same_admin]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json()["achieved"] == 0
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_change_outside_every_malicious_window_credits_nothing(client):
    session_id = _start(client)
    _fire(client, session_id, "corp-rogue-admin")
    stray = _rogue_admin_change(datetime.now(timezone.utc) - timedelta(minutes=30))
    with patch("api.views.effect.read_changes", return_value=[stray]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json()["achieved"] == 0


def test_an_option_flip_in_a_malicious_window_credits_self_registration(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-self-registration") + timedelta(seconds=1)
    flip = effect.Change(table="wp_options", kind="update", at=at,
                         columns={2: "users_can_register", 3: "1"})
    with patch("api.views.effect.read_changes", return_value=[flip]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json()["achieved"] == 1
    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {"corp-self-registration"}


def test_an_objective_is_credited_from_the_row_not_from_any_alert(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-content-write") + timedelta(seconds=1)
    new_post = effect.Change(table="wp_posts", kind="insert", at=at,
                             columns={1: "99", 8: "publish", 5: "x", 6: "Unauthorized"})
    with patch("api.views.effect.read_changes", return_value=[new_post]):
        client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert Objective.objects.filter(session_id=session_id, key="corp-content-overwrite").exists()


def test_observing_twice_credits_each_objective_once(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)
    with patch("api.views.effect.read_changes", return_value=[_rogue_admin_change(at)]):
        client.post_json(f"/api/sessions/{session_id}/objectives/")
        client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert Objective.objects.filter(session_id=session_id, key="corp-rogue-admin").count() == 1
