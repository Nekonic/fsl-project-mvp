from unittest.mock import patch

import pytest

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

def test_starting_on_the_compose_range_ignores_the_slot(client):
    first = client.post_json("/api/sessions/", {})
    second = client.post_json("/api/sessions/", {})

    assert first.status_code == 201
    assert second.status_code == 201, (
        "compose has no slot, so the many-concurrent-session behaviour must stand"
    )

def test_starting_a_session_takes_a_ready_slot(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ), patch("api.views.objectives.solved_keys", return_value=set()):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 201
    assert Session.objects.count() == 1

def test_starting_refuses_a_slot_that_is_not_ready(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(False, ["fsl-waf is REBUILD"])
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "fsl-waf is REBUILD" in response.json()["detail"]
    assert Session.objects.count() == 0, "a not-ready start must create no row"

def test_starting_refuses_a_second_open_session_on_the_cloud(client):
    Session.objects.create(scenario="juice-shop", baseline=[])
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "already open" in response.json()["detail"]
    assert Session.objects.count() == 1

def test_the_readiness_gate_runs_before_the_row_is_created(client):
    seen = {}

    def ready(adapter):
        seen["rows"] = Session.objects.count()
        return _verdict(False, ["not ready"])

    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", side_effect=ready
    ):
        client.post_json("/api/sessions/", {})

    assert seen["rows"] == 0
    assert Session.objects.count() == 0
