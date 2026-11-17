import dataclasses
import threading
from unittest.mock import patch

import pytest
import yaml

from api import reset
from api.models import Session
from range import fabric, openstack, pool, sandbox
from tests import fakecloud

BASELINE = (fakecloud.ROOT / openstack.BASELINE_RULES).read_text()


@pytest.fixture
def cloud(monkeypatch):
    fake = fakecloud.Cloud()
    server = fakecloud.serving(fake)
    runner = fakecloud.Runner()
    runner.answer(sandbox.READY, "ready\n")
    runner.answer("reload-rules", '{"return":"OK"}')
    runner.answer("cat /var/lib/suricata/rules/local.rules", BASELINE)
    monkeypatch.setattr(openstack, "execute", runner)
    monkeypatch.setattr(reset, "RESET_POLL", 0.01)
    monkeypatch.setattr(reset, "_states", {})
    openstack.forget()
    fake.runner = runner
    yield fake
    openstack.forget()
    server.shutdown()
    server.server_close()


def stacks(cloud):
    return {stack["stack_name"]: stack for stack in cloud.stacks}


def test_each_slot_is_one_stack_and_the_pool_spreads_the_wargames_over_the_slots(cloud):
    adapter = fakecloud.adapter(cloud, slots=3)

    for one in adapter.every_slot():
        assert one.ensure_slot().active

    assert {name: stack["tags"][2] for name, stack in stacks(cloud).items()} == {
        "cr-slot-1": "cr.wargame=board", "cr-slot-2": "cr.wargame=corp", "cr-slot-3": "cr.wargame=board"}
    assert [plan.wargame for plan in adapter.plan_slots()] == ["board", "corp", "board"]
    created = stacks(cloud)["cr-slot-2"]
    assert created["parameters"]["control_network"] == "net-mgmt"
    assert created["parameters"]["senders_group"] == "g-" + fabric.SENDERS_GROUP
    assert created["parameters"]["image_kali"] == "cr-kali" and created["parameters"]["flavor_waf"] == "dba.small"


def test_a_slot_is_ready_only_once_heat_completes_and_every_node_reports_its_boot(cloud):
    cloud.steps_to_complete = 3
    cloud.runner.answer(sandbox.READY, "setting-up\n")
    slot = fakecloud.adapter(cloud, slots=1)

    first = slot.ensure_slot()
    assert not first.active and pool.stack_state(first.stack) == pool.BUILDING
    while slot.plan_slot().stack != pool.COMPLETE:
        pass
    assert {status for _, _, status in slot.plan_slot().standing} == {pool.SETTING_UP}
    assert pool.phase(slot.plan_slot(), None, {"state": reset.IDLE}, {}, reset.RUNNING, reset.FAILED)[0] == "REBUILDING"
    cloud.runner.answer(sandbox.READY, "ready\n")
    assert slot.plan_slot().active
    probed = {address for address, sent in cloud.runner.ran if sandbox.READY in sent}
    assert probed == {cloud.control_address(1, node) for node in ("cr-kali", "cr-infra", "cr-waf", "cr-target")}


def test_a_node_whose_boot_failed_shows_the_slot_as_failed_to_set_up(cloud):
    cloud.runner.answer(sandbox.READY, "failed\n")
    plan = fakecloud.adapter(cloud, slots=1).ensure_slot()

    assert pool.phase(plan, None, {"state": reset.IDLE}, {}, reset.RUNNING, reset.FAILED) == (
        pool.SETUP_FAILED, [f"{host} failed its setup; {pool.SETUP_LOG} on it says why"
                            for host in ("cr-infra", "cr-kali", "cr-target", "cr-waf")])


def test_a_stack_heat_failed_is_deleted_by_the_next_ensure_and_created_again(cloud):
    cloud.fail_next_stack = "Quota exceeded for cores"
    slot = fakecloud.adapter(cloud, slots=1)
    slot.ensure_slot()
    failed = slot.plan_slot()

    assert failed.failures == ("cr-slot-1 is CREATE_FAILED: Quota exceeded for cores",)
    assert pool.phase(failed, None, {"state": reset.IDLE}, {}, reset.RUNNING, reset.FAILED)[0] == pool.SETUP_FAILED
    slot.ensure_slot()
    assert slot.plan_slot().boot == ("cr-slot-1",)
    assert slot.ensure_slot().active and slot.plan_slot().stack_id != failed.stack_id


def test_a_stack_from_another_template_or_image_is_stale_and_replaced_only_when_asked(cloud):
    fakecloud.adapter(cloud, slots=1).ensure_slot()
    newer = fakecloud.adapter(cloud, slots=1, images={"kali": "cr-kali-2026.4"})
    held = newer.plan_slot().stack_id

    assert newer.plan_slot().stale == ("cr-slot-1",)
    newer.ensure_slot(renew=False)
    assert newer.plan_slot().stack_id == held
    newer.ensure_slot()
    assert newer.ensure_slot().active and stacks(cloud)["cr-slot-1"]["parameters"]["image_kali"] == "cr-kali-2026.4"


def test_commands_reach_each_role_on_its_own_node_and_the_targets_through_docker_exec(cloud):
    slot = fakecloud.adapter(cloud, slots=2).in_slot(2)
    slot.ensure_slot()

    slot.runner("attacker")(["curl", "http://corp.com/"])
    slot.runner("corp-db")(["mysql", "-e", "select 1"])
    slot.runner("gateway")(["nginx", "-t"])
    kali, target, waf = (cloud.control_address(2, node) for node in ("cr-kali", "cr-target", "cr-waf"))

    assert cloud.runner.sent_to(kali)[-1].startswith("sudo sh -c ") and "curl http://corp.com/" in cloud.runner.sent_to(kali)[-1]
    assert cloud.runner.sent_to(target)[-1].startswith("sudo docker exec corp-db sh -c "), (
        "api/effect.py reads corp's database with the commands it ran in the container")
    assert cloud.runner.sent_to(waf)[-1].endswith("sh nginx -t")
    assert slot.address("attacker") == kali
    assert slot.terminal("cr-waf")[0] == waf and slot.terminal("cr-waf")[2] == "cr-waf"


def test_a_session_slot_opens_only_on_a_stack_built_for_its_wargame(cloud):
    slot = fakecloud.adapter(cloud, slots=1)
    slot.ensure_slot()

    slot.play("board")
    with pytest.raises(openstack.RangeUnavailable, match="slot 1 runs board, not corp"):
        slot.play("corp")


def test_the_refill_deletes_the_used_stack_creates_a_fresh_one_and_seeds_the_sensor(cloud):
    slot = fakecloud.adapter(cloud, slots=1)
    slot.ensure_slot()
    used = slot.plan_slot().stack_id
    turn = threading.RLock()

    assert reset.claim(1, "board")
    rebuilt = slot.reset_slot()
    reset.begin(slot, turn, rebuilt, claimed=True, wargame="board").join(10)

    assert rebuilt == [("cr-slot-1", used)]
    assert reset.standing(1)["state"] == reset.IDLE and reset.owed() == []
    fresh = slot.plan_slot()
    assert fresh.active and fresh.stack_id != used, "the next session gets a pristine stack, not the used one"
    infra = cloud.control_address(1, "cr-infra")
    assert any("suricatasc -c reload-rules" in sent for sent in cloud.runner.sent_to(infra))


def test_a_refill_that_heat_cannot_finish_fails_with_heat_s_reason(cloud):
    slot = fakecloud.adapter(cloud, slots=1)
    slot.ensure_slot()
    cloud.fail_next_stack = "No valid host was found"

    assert reset.claim(1)
    reset.begin(slot, threading.RLock(), slot.reset_slot(), claimed=True).join(10)

    assert reset.standing(1) == {"state": reset.FAILED,
                                 "reason": "cr-slot-1 is CREATE_FAILED: No valid host was found"}


def test_a_refill_retargets_the_slot_to_the_wargame_it_was_claimed_for(cloud):
    slot = fakecloud.adapter(cloud, slots=1)
    slot.ensure_slot()

    assert reset.claim(1, "corp")
    reset.begin(slot, threading.RLock(), slot.reset_slot(), claimed=True, wargame=reset.wanted(1)).join(10)

    assert slot.plan_slot().wargame == "corp" and slot.plan_slot().active


def test_what_earlier_ranges_left_and_slots_beyond_the_pool_are_listed_and_removed(cloud):
    wide = fakecloud.adapter(cloud, slots=2)
    for one in wide.every_slot():
        one.ensure_slot()
    cloud.servers.append({"id": "srv-range", "name": "cr-range", "status": "ACTIVE",
                          "metadata": {"cr_host": "cr-range"}, "addresses": {}})
    narrow = fakecloud.adapter(cloud, slots=1)

    listed = {(kind, why.split(":")[0]) for kind, _, why in narrow.plan_leftovers()}
    assert listed == {("stack", "cr-slot-2"), ("server", "cr-range")}
    removed = narrow.clean_leftovers()
    assert [kind for kind, _ in removed] == ["stack", "server"]
    assert set(stacks(cloud)) == {"cr-slot-1"}


def test_phases_keep_the_names_bin_cloud_and_the_console_read():
    ready = pool.Plan(standing=(("cr-waf", "s", pool.ACTIVE),), stack=pool.COMPLETE)
    idle = {"state": reset.IDLE, "reason": ""}

    def named(plan, held=None, resetting=idle, checks=None):
        return pool.phase(plan, held, resetting, checks or {"ground_truth": True, "rules_baseline": True},
                          reset.RUNNING, reset.FAILED)[0]

    assert named(ready) == "READY"
    assert named(ready, checks={"ground_truth": False}) == "CHECKING"
    assert named(ready, held=7) == "IN_USE"
    assert named(ready, resetting={"state": reset.RUNNING, "reason": ""}) == "RESETTING"
    assert named(ready, resetting={"state": reset.FAILED, "reason": "x"}) == "RESET_FAILED"
    assert named(pool.Plan(boot=("cr-slot-1",))) == "NOT_STANDING"
    assert named(pool.Plan(standing=ready.standing, stale=("cr-slot-1",))) == "STALE"
    assert named(pool.Plan(standing=(("cr-slot-1", "x", pool.BUILDING),))) == "REBUILDING"


@pytest.mark.django_db(transaction=True)
def test_a_session_for_a_wargame_no_slot_runs_rebuilds_a_free_slot_for_it(client, cloud):
    adapter = fakecloud.adapter(cloud, slots=1)
    adapter.ensure_slot()
    begun = []
    with patch("api.views.substrate", lambda: adapter), \
            patch("api.views.loot.ground_truth", lambda wargame, inside: {"admin": "x"}), \
            patch.dict(reset._states, clear=True), \
            patch("api.views.reset.begin", lambda one, turn, rebuilt, **kept: begun.append((one.slot, kept))):
        answer = client.post_json("/api/sessions/", {"scenario": "corp"})

    assert answer.status_code == 409 and "slot 1 is being built again for it" in answer.json()["detail"]
    assert begun == [(1, {"claimed": True, "wargame": "corp"})]
    assert reset.wanted(1) == "corp" and stacks(cloud)["cr-slot-1"]["stack_status"] == fakecloud.DELETING
    assert not Session.objects.exists()


def test_commands_to_a_ready_slot_ask_the_cloud_nothing_until_its_stack_is_created_again(cloud):
    fakecloud.adapter(cloud, slots=1).ensure_slot()
    asked = len(cloud.calls)
    request = fakecloud.adapter(cloud, slots=1)

    request.runner("attacker")(["true"])
    request.runner("gateway")(["true"])
    request.terminal("cr-waf")
    assert len(cloud.calls) == asked, "the node addresses are held per stack, not looked up per command"
    alias = request.terminal("cr-kali")[1]
    request.teardown_slot()
    assert openstack._held == {}, "a stack being deleted or created leaves no address behind"
    cloud.advance()
    request.ensure_slot()
    assert request.address("attacker") == cloud.control_address(1, "cr-kali")
    assert request.terminal("cr-kali")[1] != alias, "the new VM's host key is known under its own name"


def test_every_node_of_a_stack_takes_the_platform_s_own_public_key_for_its_management_user(cloud, tmp_path):
    (tmp_path / "id_ed25519").write_text("private")
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA cr-platform\n")
    adapter = fakecloud.adapter(cloud, slots=1)
    adapter.cloud = dataclasses.replace(adapter.cloud, ssh_key=str(tmp_path / "id_ed25519"))
    adapter.ensure_slot()

    servers = [resource["properties"] for resource in stacks(cloud)["cr-slot-1"]["template"]["resources"].values()
               if resource["type"] == "OS::Nova::Server"]
    assert len(servers) == 4
    for server in servers:
        [_, user] = yaml.safe_load(server["user_data"])["users"]
        assert user["name"] == "ubuntu" and user["ssh_authorized_keys"] == ["ssh-ed25519 AAAA cr-platform"]


def test_the_pool_holds_as_many_slots_of_each_wargame_as_the_cloud_settings_ask_for(cloud):
    declared = fakecloud.adapter(cloud).declared
    signed = {"keystone": "http://127.0.0.1:1", "user": "u", "password": "p", "project": "cr",
              "ssh_key": "/nonexistent", "region": "RegionOne", "interface": "public", "domain": "Default"}
    adapter = openstack.connect(declared, pool="board=3 corp=1", **signed)

    assert adapter.slots == 4 and adapter.reach.ssh_user == "ubuntu"
    assert [one.wargame for one in adapter.every_slot()] == ["board", "board", "board", "corp"]
    assert pool.assigned(5, ("board", "corp"), (("board", 3), ("corp", 1))) == ""
    with pytest.raises(openstack.RangeUnavailable, match="CR_OPENSTACK_POOL"):
        openstack.connect(declared, pool="board=0", **signed)
