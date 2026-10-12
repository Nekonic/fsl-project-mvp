import threading
import time
from unittest.mock import patch

import pytest

from api import reset
from api.models import Session
from range import slot
from range.ports import Drifted, RangeUnavailable

pytestmark = pytest.mark.django_db

ACTIVE = (("fsl-edge", "s1", "ACTIVE"), ("fsl-waf", "s2", "ACTIVE"))
REBUILDING = (("fsl-edge", "s1", "REBUILD"), ("fsl-waf", "s2", "REBUILD"))

class Slot:
    def __init__(self, configure=None, plans=None):
        self.configure = configure or (lambda: None)
        self.plans = list(plans if plans is not None else [REBUILDING])
        self.configured = 0

    def plan_slot(self):
        standing = self.plans.pop(0) if self.plans else ACTIVE
        return slot.Plan(boot=(), standing=standing, blocked=())

    def rebuild_slot(self):
        return [(host, server) for host, server, _ in ACTIVE]

    def configure_slot(self):
        self.configured += 1
        self.configure()
        return [("fsl-edge", ("sensing",))]

    def runner(self, role):
        return lambda *a, **k: None

@pytest.fixture(autouse=True)
def an_idle_reset():
    with patch.dict(reset._state, {"state": reset.IDLE, "reason": ""}), \
            patch("api.reset.RESET_POLL", 0):
        yield

def _checked(cloud):
    return patch("api.views.substrate", lambda: cloud), patch(
        "api.views._ground_truth_readable", return_value=True
    ), patch("api.views._rules_at_baseline", return_value=True)

def _ready(client, cloud):
    first, second, third = _checked(cloud)
    with first, second, third:
        return client.get("/api/range/ready/").json()

def _until_settled():
    deadline = time.monotonic() + 5
    while reset.standing()["state"] == reset.RUNNING:
        assert time.monotonic() < deadline, "the reset never finished"
        time.sleep(0.01)

def test_closing_a_session_on_the_cloud_configures_the_slot_once_its_vms_are_active(client):
    session = Session.objects.create(scenario="board", baseline=[])
    rebuilding = (("fsl-edge", "s1", "REBUILD"), ("fsl-waf", "s2", "REBUILD"))
    half = (("fsl-edge", "s1", "REBUILD"), ("fsl-waf", "s2", "ACTIVE"))
    cloud = Slot(plans=[rebuilding, half])

    with patch("api.views.substrate", lambda: cloud):
        closed = client.post_json(f"/api/sessions/{session.pk}/close/")
        _until_settled()

    assert closed.status_code == 200, closed.content
    assert cloud.configured == 1, (
        "a close rebuilds the slot from its images, which wipes the edge's "
        "configuration; nothing configured it again, so the next session open "
        "is refused until someone calls POST /api/range/configure/"
    )
    assert cloud.plans == [], "configure ran before every rebuilt VM was ACTIVE"
    assert reset.standing() == {"state": reset.IDLE, "reason": ""}

def test_while_the_reset_runs_the_range_says_it_is_resetting_and_refuses_a_session(client):
    release = threading.Event()
    cloud = Slot(configure=lambda: release.wait(5))
    worker = reset.begin(cloud, threading.RLock())
    try:
        body = _ready(client, cloud)
        first, second, third = _checked(cloud)
        with first, second, third:
            refused = client.post_json("/api/sessions/", {"scenario": "board"})
    finally:
        release.set()
        worker.join(5)

    assert body["ready"] is False
    assert body["slot"]["phase"] == "RESETTING"
    assert any("resetting" in reason for reason in body["slot"]["blocked"])
    assert refused.status_code == 409
    assert "resetting" in refused.json()["detail"], refused.content

def test_a_failed_reset_is_reported_until_configure_is_called_by_hand(client):
    def drifts():
        raise Drifted("fsl-edge did not take its configuration")

    tried = Slot(configure=drifts)
    reset.begin(tried, threading.RLock()).join(5)
    failed = _ready(client, tried)

    fixed = Slot(plans=[])
    first, second, third = _checked(fixed)
    with first, second, third:
        retried = client.post_json("/api/range/configure/")
        after = client.get("/api/range/ready/").json()

    assert failed["ready"] is False
    assert failed["slot"]["phase"] == "RESET_FAILED"
    assert any("fsl-edge did not take its configuration" in reason
               for reason in failed["slot"]["blocked"])
    assert retried.status_code == 200
    assert after["ready"] is True and after["slot"]["phase"] == "READY"

def test_the_reset_retries_configure_while_the_rebuilt_vms_do_not_answer_ssh(client):
    unanswered = [RangeUnavailable("fsl-edge never reported the command finishing")] * 2

    def answers_later():
        if unanswered:
            raise unanswered.pop()

    cloud = Slot(configure=answers_later)
    reset.begin(cloud, threading.RLock()).join(5)

    assert cloud.configured == 3
    assert reset.standing()["state"] == reset.IDLE

def test_the_reset_does_not_configure_a_vm_nova_still_shows_active_from_before_its_rebuild(client):
    edge_lags = (("fsl-edge", "s1", "ACTIVE"), ("fsl-waf", "s2", "REBUILD"))
    edge_rebuilds = (("fsl-edge", "s1", "REBUILD"), ("fsl-waf", "s2", "ACTIVE"))
    configured_after = []
    cloud = Slot(plans=[ACTIVE, edge_lags, edge_rebuilds])
    cloud.configure = lambda: configured_after.append(list(cloud.plans))

    reset.begin(cloud, threading.RLock()).join(5)

    assert configured_after == [[]], (
        "configure ran while Nova still showed a VM ACTIVE that it had not yet "
        "been seen rebuilding, so it may have configured the VM from before the "
        "rebuild and left the rebuilt one bare"
    )
    assert reset.standing()["state"] == reset.IDLE

def test_a_vm_nova_never_shows_rebuilding_fails_the_reset_instead_of_configuring_it(client):
    cloud = Slot(plans=[])
    with patch("api.reset.REBUILD_SHOWN", 0):
        reset.begin(cloud, threading.RLock()).join(5)

    assert cloud.configured == 0
    assert reset.standing()["state"] == reset.FAILED
    assert "never showed" in reset.standing()["reason"]

def test_while_the_reset_runs_readiness_does_not_read_the_vms_being_rebuilt(client):
    release = threading.Event()
    cloud = Slot(configure=lambda: release.wait(5))
    worker = reset.begin(cloud, threading.RLock())
    try:
        with patch("api.views.substrate", lambda: cloud), \
                patch("api.views._ground_truth_readable") as truth, \
                patch("api.views._rules_at_baseline") as rules:
            body = client.get("/api/range/ready/").json()
    finally:
        release.set()
        worker.join(5)

    assert body["slot"]["phase"] == "RESETTING" and body["ready"] is False
    assert not truth.called and not rules.called, (
        "readiness read the target and the sensors over ssh while their VMs "
        "were mid-rebuild, which only waits out timeouts"
    )
    assert body["slot"]["checks"]["ground_truth"] is None
    assert not any("ground truth" in reason for reason in body["slot"]["blocked"])

class ResetsInPlace(Slot):
    def __init__(self, plans, in_place=None, rebuilt=None):
        super().__init__(plans=plans)
        self.in_place = in_place or (lambda: None)
        self.rebuilt_step = rebuilt or (lambda hosts: None)
        self.configured_rebuilt = []
        self.reset = 0

    def reset_in_place(self):
        self.reset += 1
        self.in_place()
        return [("fsl-edge", ("reset in place",))]

    def configure_rebuilt(self, hosts):
        self.configured_rebuilt.append(list(hosts))
        self.rebuilt_step(hosts)
        return [(host, ()) for host in hosts]

WAF_REBUILDING = (("fsl-edge", "s1", "ACTIVE"), ("fsl-waf", "s2", "REBUILD"))

def test_only_the_vms_the_close_rebuilt_must_be_seen_rebuilding(client):
    cloud = ResetsInPlace(plans=[WAF_REBUILDING])

    with patch("api.reset.REBUILD_SHOWN", 0):
        reset.begin(cloud, threading.RLock(), [("fsl-waf", "s2")]).join(5)

    assert reset.standing() == {"state": reset.IDLE, "reason": ""}, (
        "the edge resets in place, so Nova never shows it rebuilding; waiting for "
        "that failed every reset"
    )
    assert cloud.reset == 1 and cloud.configured_rebuilt == [["fsl-waf"]]
    assert cloud.configured == 0, "the whole slot is not configured again on top"

def test_the_in_place_reset_runs_while_the_rebuilt_vms_come_back(client):
    rebuilt_configured = threading.Event()
    seen = {}

    def in_place():
        seen["rebuilding"] = list(cloud.plans)
        seen["overlapped"] = rebuilt_configured.wait(5)

    cloud = ResetsInPlace(plans=[WAF_REBUILDING, WAF_REBUILDING],
                          in_place=in_place, rebuilt=lambda hosts: rebuilt_configured.set())
    started = time.monotonic()
    reset.begin(cloud, threading.RLock(), [("fsl-waf", "s2")]).join(10)

    assert seen["rebuilding"], "the in-place reset waited for Nova to finish the rebuild"
    assert seen["overlapped"] and time.monotonic() - started < 5, (
        "the in-place reset and the rebuilt VMs' configure ran one after the other"
    )
    assert reset.standing()["state"] == reset.IDLE

def test_an_in_place_reset_that_fails_fails_the_reset_with_its_reason(client):
    def drifts():
        raise Drifted("fsl-wargame-host did not clear its wargames")

    cloud = ResetsInPlace(plans=[WAF_REBUILDING], in_place=drifts)
    reset.begin(cloud, threading.RLock(), [("fsl-waf", "s2")]).join(5)

    assert reset.standing()["state"] == reset.FAILED
    assert "did not clear its wargames" in reset.standing()["reason"]
    assert cloud.configured_rebuilt == [["fsl-waf"]], "the rebuilt side still ran to the end"

def test_closing_on_the_cloud_rebuilds_what_the_adapter_names_and_resets_the_rest(client):
    session = Session.objects.create(scenario="board", baseline=[])

    class Cloud(ResetsInPlace):
        def reset_slot(self):
            return [("fsl-waf", "s2")]

        def rebuild_slot(self):
            raise AssertionError("a close rebuilt every VM")

    cloud = Cloud(plans=[WAF_REBUILDING])
    with patch("api.views.substrate", lambda: cloud), patch("api.reset.REBUILD_SHOWN", 0):
        closed = client.post_json(f"/api/sessions/{session.pk}/close/")
        _until_settled()

    assert closed.status_code == 200, closed.content
    assert closed.json()["rebuilding"] == [{"host": "fsl-waf", "server": "s2"}]
    assert cloud.reset == 1 and cloud.configured_rebuilt == [["fsl-waf"]]
    assert reset.standing()["state"] == reset.IDLE
