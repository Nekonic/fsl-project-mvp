import threading
from unittest.mock import patch

import pytest

from api import loot, views
from range import pool
from range.ports import RangeUnavailable
from rules.suricata import RulesUnreadable

URL = "/api/range/ready/"

pytestmark = pytest.mark.django_db

class Cloud:
    def __init__(self, standing=(("cr-range", "s1", "ACTIVE"),), boot=(), blocked=(), stale=()):
        self._plan = pool.Plan(boot=boot, standing=standing, blocked=blocked, stale=stale)

    def plan_slot(self):
        return self._plan

    def runner(self, role):
        return lambda *a, **k: None

def _get(client, cloud):
    with patch("api.views.substrate", lambda: cloud), patch(
        "api.views._ground_truth_readable", return_value=True
    ), patch("api.views._rules_at_baseline", return_value=True):
        return client.get(URL)

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
    (Cloud(standing=(("cr-range", "s1", "SETTING_UP"),)), "REBUILDING", "cr-range is SETTING_UP"),
    (Cloud(boot=("cr-range",), blocked=("the range host pulls the images by the range images' tag",)), "NOT_STANDING",
     "the range host pulls the images"),
    (Cloud(stale=("cr-range",)), "STALE", "cr-range was created from another template"),
    (Cloud(standing=(("cr-range", "s1", "SETUP_FAILED"),)), "SETUP_FAILED", "cr-range failed its setup"),
], ids=["rebuilding", "to-boot", "older-image", "setup-failed"])
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

def test_a_corp_slot_is_ready_once_corp_s_own_ground_truth_reads(client):
    cloud = Cloud()
    cloud._plan = pool.Plan(standing=(("cr-target", "s1", "ACTIVE"),), wargame="corp")
    asked = []

    def baseline(adapter, wargame):
        asked.append(wargame)
        return {"admins": [1]} if wargame == "corp" else None

    with patch("api.views.substrate", lambda: cloud), patch("api.views._baseline", baseline), \
            patch("api.views._rules_at_baseline", return_value=True):
        body = client.get(URL).json()

    assert asked == ["corp"], "a corp slot runs no board, so its board ground truth never reads"
    assert body["slot"]["checks"]["ground_truth"] is True

class Counted(Cloud):
    def __init__(self):
        super().__init__()
        self.asked = 0
        self.failing = False

    def plan_slot(self):
        self.asked += 1
        if self.failing:
            raise RangeUnavailable("the cloud's API did not answer")
        return super().plan_slot()

def _refreshed_behind(client, cloud):
    views._ready_kept["verdict"]["at"] -= views.READY_FRESH
    with patch("api.views.substrate", lambda: cloud), patch(
        "api.views._ground_truth_readable", return_value=True
    ), patch("api.views._rules_at_baseline", return_value=True):
        answer = client.get(URL)
        for refresh in [thread for thread in threading.enumerate() if thread.name == "cr-ready-refresh"]:
            refresh.join(5)
    return answer

def test_readiness_polls_reach_the_cloud_once_while_the_answer_is_fresh_and_a_stale_one_is_refreshed_behind_it(client):
    cloud = Counted()
    first, again = _get(client, cloud).json(), _get(client, cloud).json()
    assert cloud.asked == 1 and first == again, (
        "2026-11-18: every GET /api/range/ready/ listed the Heat stacks and read each free slot's target and sensor "
        "over SSH, 13-26 s per call, holding one of the platform's 16 request threads each time")

    stale = _refreshed_behind(client, cloud).json()

    assert stale == first and cloud.asked == 2

def test_a_refresh_the_cloud_refused_is_answered_as_refused_not_as_the_last_ready(client):
    cloud = Counted()
    assert _get(client, cloud).json()["ready"] is True
    cloud.failing = True
    _refreshed_behind(client, cloud)

    answer = _get(client, cloud)

    assert answer.status_code == 503 and "did not answer" in answer.json()["detail"]
