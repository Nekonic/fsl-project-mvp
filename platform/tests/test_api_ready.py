from unittest.mock import patch

import pytest

from api import loot
from range import slot
from rules.suricata import RulesUnreadable

URL = "/api/range/ready/"

pytestmark = pytest.mark.django_db

class Cloud:
    def __init__(self, standing=(("fsl-waf", "s1", "ACTIVE"),), boot=(), blocked=()):
        self._plan = slot.Plan(boot=boot, standing=standing, blocked=blocked)

    def plan_slot(self):
        return self._plan

    def runner(self, role):
        return lambda *a, **k: None

def _get(client, cloud):
    with patch("api.views.substrate", lambda: cloud), patch(
        "api.views._ground_truth_readable", return_value=True
    ), patch("api.views._rules_at_baseline", return_value=True):
        return client.get(URL)

def test_the_compose_range_is_always_ready(client):
    answer = client.get(URL)

    assert answer.status_code == 200
    assert answer.json() == {"ready": True, "substrate": "compose", "slot": None, "max_sessions": 2}


def test_a_standing_active_range_that_passes_its_checks_is_ready(client):
    body = _get(client, Cloud()).json()

    assert body["ready"] is True
    assert body["substrate"] == "openstack"
    assert body["slot"]["phase"] == "READY"
    assert body["slot"]["checks"] == {
        "active": True, "ground_truth": True, "rules_baseline": True
    }
    assert body["slot"]["blocked"] == []

@pytest.mark.parametrize("cloud, phase, reason", [
    (Cloud(standing=(("fsl-waf", "s1", "REBUILD"),)), "REBUILDING", "fsl-waf"),
    (Cloud(boot=("fsl-wg-board",), blocked=("image fsl-wg-board is not ready",)), "NOT_STANDING",
     "image fsl-wg-board is not ready"),
], ids=["rebuilding", "to-boot"])
def test_a_slot_not_standing_ready_is_not_ready_and_says_why(client, cloud, phase, reason):
    body = _get(client, cloud).json()

    assert body["ready"] is False
    assert body["slot"]["phase"] == phase
    assert any(reason in blocked for blocked in body["slot"]["blocked"])

@pytest.mark.django_db
def test_an_unreadable_signal_degrades_to_not_ready_never_a_500(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views.loot.ground_truth", side_effect=loot.GroundTruthUnavailable("board down")
    ), patch("api.views.suricata.current", side_effect=RulesUnreadable("no sensor")):
        answer = client.get(URL)

    assert answer.status_code == 200
    body = answer.json()
    assert body["ready"] is False
    assert body["slot"]["checks"]["ground_truth"] is False
    assert body["slot"]["checks"]["rules_baseline"] is False
