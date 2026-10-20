from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Session
from range import slot

pytestmark = pytest.mark.django_db

class Cloud:
    def plan_slot(self):
        return slot.Plan(standing=(("fsl-waf", "s1", "ACTIVE"),))

    def runner(self, role):
        return lambda *a, **k: None

def _verdict(ready, blocked=()):
    return {
        "ready": ready,
        "substrate": "openstack",
        "slot": {"phase": "READY" if ready else "CHECKING",
                 "standing": [], "checks": {}, "blocked": list(blocked)},
    }

class Shared:
    def runner(self, role):
        return lambda *a, **k: None

def test_starting_refuses_a_second_open_session_on_a_shared_range(client):
    with patch("api.views.substrate", lambda: Shared()):
        first = client.post_json("/api/sessions/", {})
        second = client.post_json("/api/sessions/", {})

    assert first.status_code == 201
    assert second.status_code == 409, (
        "a range with one target for every session would score the second "
        "session against the first one's traffic"
    )
    assert "already open" in second.json()["detail"]
    assert Session.objects.filter(ended_at=None).count() == 1

def test_starting_refuses_a_slot_that_is_not_ready(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(False, ["fsl-waf is REBUILD"])
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "fsl-waf is REBUILD" in response.json()["detail"]
    assert Session.objects.count() == 0, "a not-ready start must create no row"

def test_starting_refuses_a_second_open_session_on_the_cloud(client):
    Session.objects.create(scenario="board", baseline=[])
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "already open" in response.json()["detail"]
    assert Session.objects.count() == 1

def test_closing_a_session_frees_a_place_under_the_cap(client):
    first, _ = [client.post_json("/api/sessions/", {}).json()["id"] for _ in range(2)]
    client.post_json(f"/api/sessions/{first}/close/", {})
    third = client.post_json("/api/sessions/", {})

    assert third.status_code == 201, third.content

def test_an_openstack_session_starts_with_the_attacker_at_the_front_door(client):
    aimed = []

    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ), patch("api.views.loot.ground_truth", return_value={}), patch(
        "api.views._aim_attacker", lambda adapter: aimed.append(adapter)
    ):
        opened = client.post_json("/api/sessions/", {})

    assert opened.status_code == 201
    assert len(aimed) == 1, (
        "the rebuilt attacker box leaves from whichever address DHCP made primary, "
        "not the declared default origin, so an attack sent with no origin is "
        "placed somewhere the range never chose"
    )
