import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from api import reachability, reset, views
from api.management.commands import run_on_role
from api.models import Session, Suppression
from range import slot
from range.ports import Node, Ran, Segment

pytestmark = pytest.mark.django_db(transaction=True)

BASELINE = (Path(__file__).resolve().parents[2] / "deploy/suricata/rules/local.rules").read_text()
STANDING = (("fsl-waf", "s-fsl-waf", "ACTIVE"), ("fsl-platform", "s-fsl-platform", "ACTIVE"))


class Slot:
    def __init__(self, cloud, number):
        self.cloud, self.slot = cloud, number

    @property
    def slots(self):
        return self.cloud.count

    def in_slot(self, number):
        return self.cloud.in_slot(number)

    def plan_slot(self):
        return self.cloud.plans[self.slot - 1]

    def address(self, role):
        return f"10.31.{self.slot}.{len(role)}"

    def segments(self):
        return (Segment(id="mgmt", name="Management", subnet="10.31.0.0/16",
                        nodes=(Node("fsl-waf", f"10.31.{self.slot}.9"),)),)

    def runner(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.cloud.ran.append((self.slot, role, argv))
            if self.cloud.hold and argv[:1] == ["suricata"]:
                time.sleep(self.cloud.hold)
            if argv[:1] == ["cat"]:
                return Ran(0, BASELINE)
            if "reload-rules" in " ".join(argv):
                return Ran(0, '{"return":"OK"}')
            return Ran(0, "")
        return run

    def reset_slot(self):
        self.cloud.reset.append(self.slot)
        return [("fsl-waf", f"s{self.slot}")]

    def rebuild_slot(self):
        return self.reset_slot()

    def configure_slot(self):
        self.cloud.configured.append(self.slot)
        return [("fsl-waf", ("configured",))]

    def ensure_slot(self):
        self.cloud.ensured.append(self.slot)
        return self.plan_slot()


class Cloud(Slot):
    def __init__(self, slots=2):
        super().__init__(self, 1)
        self.count = slots
        self.max_sessions = slots
        self.plans = [slot.Plan(standing=STANDING, slot=n) for n in range(1, slots + 1)]
        self.ran, self.reset, self.configured, self.ensured = [], [], [], []
        self.hold = 0

    def in_slot(self, number):
        return Slot(self, number)

    def every_slot(self):
        return [Slot(self, n) for n in range(1, self.count + 1)]

    def plan_slots(self):
        return list(self.plans)


@pytest.fixture
def cloud():
    held = Cloud()
    with patch("api.views.substrate", lambda: held), \
            patch("api.views._aim_attacker", lambda adapter: None), \
            patch("api.views.loot.ground_truth", lambda wargame, host: {"admin": host}), \
            patch.dict(reset._states, clear=True), \
            patch("api.views.reset.begin", lambda adapter, turn, rebuilt: held.reset.append(("begun", adapter.slot))):
        yield held


def opened(client):
    answer = client.post_json("/api/sessions/", {})
    assert answer.status_code == 201, answer.content
    return Session.objects.get(pk=answer.json()["id"])


def test_two_sessions_open_at_once_each_on_its_own_slot(client, cloud):
    first, second = opened(client), opened(client)
    third = client.post_json("/api/sessions/", {})

    assert (first.slot, second.slot) == (1, 2)
    assert first.baseline == {"admin": "10.31.1.5"} and second.baseline == {"admin": "10.31.2.5"}, (
        "each session's ground truth is read from its own slot's target"
    )
    assert third.status_code == 409 and "already open" in third.json()["detail"]


def test_an_open_skips_a_slot_that_is_resetting_and_takes_the_next_ready_one(client, cloud):
    reset._of(1).update(state=reset.RUNNING)

    assert opened(client).slot == 2


def test_no_ready_slot_refuses_the_open_with_the_resetting_reason(client, cloud):
    reset._of(1).update(state=reset.RUNNING)
    reset._of(2).update(state=reset.RUNNING)

    refused = client.post_json("/api/sessions/", {})

    assert refused.status_code == 409 and "resetting" in refused.json()["detail"]
    assert Session.objects.count() == 0


def test_closing_a_session_resets_its_own_slot_only_and_lifts_only_its_suppressions(client, cloud):
    first, second = opened(client), opened(client)
    mine = Suppression.objects.create(session=second, sid=1, original="", expires_at="2099-01-01T00:00:00Z")
    theirs = Suppression.objects.create(session=first, sid=2, original="", expires_at="2099-01-01T00:00:00Z")

    client.post_json(f"/api/sessions/{second.pk}/close/")

    assert cloud.reset == [2, ("begun", 2)]
    mine.refresh_from_db(), theirs.refresh_from_db()
    assert mine.restored_at is not None
    assert theirs.restored_at is None, (
        "the other slot's sensor still runs without that rule; marking it restored would "
        "leave its session with a hole the platform no longer reports"
    )


def test_readiness_lists_every_slot_and_who_holds_it(client, cloud):
    with patch("api.views._ground_truth_readable", return_value=True), \
            patch("api.views._rules_at_baseline", return_value=True):
        before = client.get("/api/range/ready/").json()
        first = opened(client)
        between = client.get("/api/range/ready/").json()
        opened(client)
        full = client.get("/api/range/ready/").json()

    assert before["ready"] and before["max_sessions"] == 2
    assert [s["number"] for s in before["slots"]] == [1, 2]
    assert between["ready"] and between["slot"]["number"] == 2
    assert between["slots"][0]["session"] == first.pk and between["slots"][0]["phase"] == "IN_USE"
    assert not full["ready"] and {s["phase"] for s in full["slots"]} == {"IN_USE"}


def test_a_session_s_rule_calls_reach_its_own_slot_s_sensor(client, cloud):
    opened(client)
    second = opened(client)
    cloud.ran.clear()

    client.get(f"/api/rules/?session={second.pk}")

    assert {(number, role) for number, role, _ in cloud.ran} == {(2, "sensor")}


def test_a_rule_change_on_one_slot_does_not_wait_for_another_slot_s_reset(client, cloud):
    first, second = opened(client), opened(client)
    holding, done = threading.Event(), threading.Event()

    def resetting():
        with views._turn(first.slot):
            holding.set()
            done.wait(5)

    held = threading.Thread(target=resetting)
    held.start()
    holding.wait()
    started = time.monotonic()
    answer = client.post_json("/api/rules/validate/", {"content": BASELINE, "session": second.pk})
    took = time.monotonic() - started
    done.set()
    held.join()

    assert answer.status_code == 200
    assert took < 2, "slot 1's reset holds slot 1's turn; slot 2's session works meanwhile"


def test_the_slot_endpoints_act_on_one_slot_or_every_slot(client, cloud):
    one = client.get("/api/range/slot/?slot=2").json()
    every = client.post_json("/api/range/slot/").json()
    configured = client.post_json("/api/range/configure/?slot=2").json()

    assert one["slot"] == 2 and [s["host"] for s in one["standing"]] == ["fsl-waf-2", "fsl-platform"]
    assert sorted(cloud.ensured) == [1, 2] and [s["slot"] for s in every["slots"]] == [1, 2]
    assert cloud.configured == [2] and configured["configured"][0]["host"] == "fsl-waf-2"
    assert client.get("/api/range/slot/?slot=3").status_code == 400


def test_a_session_reads_its_alerts_from_its_own_slot_s_index(client, cloud, settings):
    settings.ELASTIC_SESSION_INDEX = "fsl-logs-slot{slot}-*"
    opened(client)
    second = opened(client)
    read = []

    with patch("api.views.elastic.fetch", lambda url, index, *a, **k: read.append(index) or ([], None)):
        client.post_json(f"/api/sessions/{second.pk}/ingest/")

    assert read == ["fsl-logs-slot2-*"]


def test_the_openstack_session_index_is_by_slot_and_the_collector_names_the_slot():
    import subprocess
    import os
    said = subprocess.run(
        [os.sys.executable, "-c", "import django; django.setup(); from django.conf import settings; "
                                  "print(settings.ELASTIC_SESSION_INDEX)"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "fsl.settings",
             "FSL_SUBSTRATE": "range.openstack.connect", "PYTHONPATH": ".."},
    )
    assert said.stdout.strip() == "fsl-logs-slot{slot}-*", said.stderr[-300:]


def test_run_on_role_runs_on_the_slot_the_named_session_holds(client, cloud, monkeypatch):
    opened(client)
    second = opened(client)
    monkeypatch.setattr(run_on_role, "substrate", lambda: cloud)

    call_command("run_on_role", "attacker", json.dumps(["true"]), "--session", str(second.pk),
                 stdout=io.StringIO())
    call_command("run_on_role", "attacker", json.dumps(["true"]), "--slot", "1", stdout=io.StringIO())

    assert [(number, role) for number, role, _ in cloud.ran[-2:]] == [(2, "attacker"), (1, "attacker")]
    with pytest.raises(CommandError, match="--session or --slot"):
        call_command("run_on_role", "attacker", json.dumps(["true"]), stdout=io.StringIO())


def test_requests_from_any_slot_s_hosts_are_refused(cloud, monkeypatch):
    monkeypatch.setattr(reachability, "substrate", lambda: cloud)
    monkeypatch.setattr(reachability, "_cached", (0.0, frozenset()))

    assert {"10.31.1.9", "10.31.2.9"} <= reachability.scored_hosts()


def test_a_reset_s_state_is_kept_per_slot():
    with patch.dict(reset._states, clear=True):
        reset._of(2).update(state=reset.FAILED, reason="edge gone")

        assert reset.standing(1)["state"] == reset.IDLE
        assert reset.standing(2) == {"state": reset.FAILED, "reason": "edge gone"}
        reset.configured_by_hand(2)
        assert reset.standing(2)["state"] == reset.IDLE
