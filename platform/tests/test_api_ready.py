from unittest.mock import patch

import pytest

from objectives import ObjectivesUnavailable
from range import slot
from rules.suricata import RulesUnreadable

URL = "/api/range/ready/"

class Cloud:
    def __init__(self, standing=(("fsl-waf", "s1", "ACTIVE"),), boot=(), blocked=()):
        self._plan = slot.Plan(boot=boot, standing=standing, blocked=blocked)

    def plan_slot(self):
        return self._plan

    def runner(self, role):
        return lambda *a, **k: None

def _get(client, cloud, nothing_solved=True, rules_baseline=True):
    with patch("api.views.substrate", lambda: cloud), patch(
        "api.views._nothing_solved", return_value=nothing_solved
    ), patch("api.views._rules_at_baseline", return_value=rules_baseline):
        return client.get(URL)

def test_the_compose_range_is_always_ready(client):
    answer = client.get(URL)

    assert answer.status_code == 200
    assert answer.json() == {"ready": True, "substrate": "compose", "slot": None}

def test_reading_readiness_is_only_a_get(client):
    assert client.post_json(URL).status_code == 405

def test_a_standing_active_range_that_passes_its_checks_is_ready(client):
    body = _get(client, Cloud()).json()

    assert body["ready"] is True
    assert body["substrate"] == "openstack"
    assert body["slot"]["phase"] == "READY"
    assert body["slot"]["checks"] == {
        "active": True, "nothing_solved": True, "rules_baseline": True
    }
    assert body["slot"]["blocked"] == []

def test_a_slot_with_a_rebuilding_vm_is_not_ready(client):
    body = _get(client, Cloud(standing=(("fsl-waf", "s1", "REBUILD"),))).json()

    assert body["ready"] is False
    assert body["slot"]["phase"] == "REBUILDING"
    assert any("fsl-waf" in reason for reason in body["slot"]["blocked"])

def test_a_slot_still_to_boot_is_not_ready(client):
    body = _get(client, Cloud(boot=("fsl-wiki",), blocked=("image fsl-board is not ready",))).json()

    assert body["ready"] is False
    assert body["slot"]["phase"] == "NOT_STANDING"
    assert "image fsl-board is not ready" in body["slot"]["blocked"]

def test_a_solved_objective_leaves_the_range_not_ready(client):
    body = _get(client, Cloud(), nothing_solved=False).json()

    assert body["ready"] is False
    assert body["slot"]["phase"] == "CHECKING"
    assert body["slot"]["checks"]["nothing_solved"] is False
    assert any("clean" in reason for reason in body["slot"]["blocked"])

def test_rules_off_baseline_leave_the_range_not_ready(client):
    body = _get(client, Cloud(), rules_baseline=False).json()

    assert body["ready"] is False
    assert body["slot"]["checks"]["rules_baseline"] is False

@pytest.mark.django_db
def test_an_unreadable_signal_degrades_to_not_ready_never_a_500(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views.objectives.solved_keys", side_effect=ObjectivesUnavailable("juice-shop down")
    ), patch("api.views.suricata.current", side_effect=RulesUnreadable("no sensor")):
        answer = client.get(URL)

    assert answer.status_code == 200
    body = answer.json()
    assert body["ready"] is False
    assert body["slot"]["checks"]["nothing_solved"] is False
    assert body["slot"]["checks"]["rules_baseline"] is False
