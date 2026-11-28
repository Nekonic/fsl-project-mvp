import dataclasses

import pytest
import yaml

from cr.config import OpenStackConfig
from sandbox import fabric
from sandbox import openstack, pool, stack_plan
from testing import fakecloud

BASELINE = (fakecloud.ROOT / stack_plan.read(fakecloud.ROOT, "board").filling("sensor").baseline).read_text()


@pytest.fixture
def cloud(monkeypatch):
    fake = fakecloud.Cloud()
    server = fakecloud.serving(fake)
    runner = fakecloud.Runner()
    runner.answer(stack_plan.READY, "ready\n")
    runner.answer("reload-rules", '{"return":"OK"}')
    runner.answer("cat /var/lib/suricata/rules/local.rules", BASELINE)
    monkeypatch.setattr(openstack, "execute", runner)
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
    assert created["parameters"]["image_kali"] == "cr-kali-bake1" and created["parameters"]["flavor_waf"] == "dba.small"


def test_the_slots_share_three_lan_security_groups_and_the_fabric_teardown_removes_them(cloud):
    adapter = fakecloud.adapter(cloud, slots=3)
    for one in adapter.every_slot():
        one.ensure_slot()

    lan_groups = {group["id"]: group for group in cloud.groups if group["name"].startswith(fabric.LAN_GROUP_PREFIX)}
    assert len(lan_groups) == 3, "a pool of any size adds three groups, not five per slot"
    used = {group for port in cloud.ports for group in port.get("security_groups") or ()}
    assert set(lan_groups) <= used
    steps = fabric.teardown(adapter.declared, [], [], [], cloud.groups)
    assert {("group", ident) for ident in lan_groups} <= set(steps)


def test_a_stack_from_another_template_or_image_is_stale_and_replaced_only_when_asked(cloud):
    fakecloud.adapter(cloud, slots=1).ensure_slot()
    cloud.images.append({"id": "img-kali-2", "name": "cr-kali-2026.4", "status": "active"})
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
    slot.runner("waf")(["nginx", "-t"])
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


def test_a_slot_whose_role_image_glance_does_not_hold_is_blocked_naming_it(cloud):
    cloud.images = [image for image in cloud.images if image["name"] != "cr-target-bake1"]

    assert fakecloud.adapter(cloud, slots=1).plan_slot().blocked == (
        "no active image cr-target-bake1 in Glance for the slot's target; bake it from deploy/roles/target/ "
        "or name another in compute.images.target",)
    assert not [stack for stack in cloud.stacks], "Heat is asked for nothing it would fail on"


def test_commands_to_a_ready_slot_ask_the_cloud_nothing_until_its_stack_is_created_again(cloud):
    fakecloud.adapter(cloud, slots=1).ensure_slot()
    asked = len(cloud.calls)
    request = fakecloud.adapter(cloud, slots=1)

    request.runner("attacker")(["true"])
    request.runner("waf")(["true"])
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
    signed = OpenStackConfig(keystone="http://127.0.0.1:1", user="u", password="p", project="cr",
                             ssh_key="/nonexistent", region="RegionOne", interface="public", domain="Default")
    adapter = openstack.connect(dataclasses.replace(signed, pool="board=3 corp=1"), declared)

    assert adapter.slots == 4 and adapter.reach.ssh_user == "ubuntu"
    assert [one.wargame for one in adapter.every_slot()] == ["board", "board", "board", "corp"]
    assert pool.assigned(5, ("board", "corp"), (("board", 3), ("corp", 1))) == ""
    with pytest.raises(openstack.RangeUnavailable, match="CR_OPENSTACK_POOL"):
        openstack.connect(dataclasses.replace(signed, pool="board=0"), declared)


def test_a_slot_s_sensor_starts_on_the_rules_its_own_wargame_names(cloud):
    adapter = fakecloud.adapter(cloud, slots=2)
    rules = fakecloud.ROOT / "deploy/suricata/rules"

    started = {one.wargame: one.baseline_rules("sensor") for one in adapter.every_slot()}

    assert started == {"board": (rules / "board.rules").read_text(), "corp": (rules / "corp.rules").read_text()}
    assert started["board"] != started["corp"], "a corp round would start on the board's signatures"
