import importlib.util
import itertools
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/cloud"


def command():
    loader = SourceFileLoader("fsl_cloud_command", str(COMMAND))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("fsl_cloud_command", loader))
    loader.exec_module(module)
    return module


def image(state, host="fsl-edge", bundle="d1", detail=""):
    return {"host": host, "bundle": bundle, "state": state, "image": "", "builder": "", "detail": detail}


class Platform:
    def __init__(self, images=None, fabric=None, slot=None, ready=None, configure=None):
        self.calls = []
        self.images = iter(images or [{"images": [image("ready")], "leftovers": [], "clean": True}])
        self.fabric = fabric or {"drifted": [], "clean": True}
        self.slot = slot or {"blocked": [], "clean": True}
        self.ready = iter(ready or [
            {"ready": False, "slot": {"phase": "NOT_STANDING"}},
            {"ready": False, "slot": {"phase": "CHECKING"}},
            {"ready": True, "slot": {"phase": "READY"}},
        ])
        self.configure = iter(configure or [(200, {"configured": []})])

    def __call__(self, verb, path):
        self.calls.append((verb, path))
        if (verb, path) == ("POST", "/fabric/"):
            return 200, self.fabric
        if (verb, path) == ("POST", "/images/"):
            return 200, next(self.images)
        if (verb, path) == ("POST", "/slot/"):
            return 200, self.slot
        if (verb, path) == ("GET", "/ready/"):
            return 200, next(self.ready)
        if (verb, path) == ("POST", "/configure/"):
            return next(self.configure)
        return 200, {"removed": []}


def converge(platform):
    clock = itertools.count()
    return command().converge(platform, sleep=lambda seconds: None, clock=lambda: next(clock))


def test_up_builds_the_range_in_the_order_the_platform_requires():
    platform = Platform()

    assert converge(platform)["ready"]

    order = [call for call in platform.calls if call[0] == "POST"]
    assert order == [("POST", "/fabric/"), ("POST", "/images/"), ("POST", "/slot/"),
                     ("POST", "/configure/")]
    first_configure = platform.calls.index(("POST", "/configure/"))
    assert platform.calls[first_configure - 1] == ("GET", "/ready/"), (
        "configure ssh-es to the slot's VMs, so it waits until Nova says they stand"
    )


@pytest.mark.parametrize("bad, why", [
    (image("failed", detail="checksum did NOT match"), "checksum did NOT match"),
    (image("missing", bundle=""), "no script builds it"),
])
def test_a_failed_image_stops_up_with_why(bad, why):
    platform = Platform(images=[{"images": [bad], "leftovers": [], "clean": False}])

    with pytest.raises(SystemExit, match=why):
        converge(platform)
    assert ("POST", "/slot/") not in platform.calls


def test_leftovers_are_cleaned_only_once_the_range_stands_on_the_new_images():
    platform = Platform(images=[
        {"images": [image("ready")], "leftovers": [{"kind": "image", "id": "img-old"}], "clean": False},
    ])

    converge(platform)

    assert platform.calls.index(("DELETE", "/images/")) > platform.calls.index(("POST", "/configure/"))
    assert platform.calls[-1] == ("DELETE", "/images/")
    assert platform.calls.count(("POST", "/images/")) == 1


def test_a_ready_image_whose_builder_is_still_there_is_asked_for_again():
    with_builder = dict(image("ready"), builder="srv-1")
    platform = Platform(images=[
        {"images": [with_builder], "leftovers": [], "clean": False},
        {"images": [image("ready")], "leftovers": [], "clean": True},
    ])

    converge(platform)

    assert platform.calls.count(("POST", "/images/")) == 2


def test_a_drifted_fabric_stops_up_before_any_image_is_built():
    platform = Platform(fabric={"drifted": ["keypair fsl-platform holds another public key"]})

    with pytest.raises(SystemExit, match="another public key"):
        converge(platform)
    assert platform.calls == [("POST", "/fabric/")]


def test_configure_is_retried_while_the_vms_ssh_is_not_up_yet_and_a_refusal_stops_up():
    platform = Platform(configure=[(503, {"detail": "fsl-edge never reported the command finishing"}),
                                   (200, {"configured": []})])

    converge(platform)

    assert platform.calls.count(("POST", "/configure/")) == 2
    with pytest.raises(SystemExit, match="did not take its configuration"):
        converge(Platform(configure=[(409, {"detail": "fsl-edge did not take its configuration"})]))


class Cli:
    def __init__(self, servers=b"[]", status=b"CREATE_COMPLETE", address=b"203.0.113.7",
                 network=b"net-stack"):
        self.ran = []
        self.answers = {"list": servers, "show": status, "output": address, "resource": network}

    def __call__(self, argv, stdin=None, check=True):
        self.ran.append(argv)
        if argv[1:3] == ["network", "show"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"fsl-platform\n")
        said = self.answers.get(argv[2], b"")
        return subprocess.CompletedProcess(argv, 0 if said is not None else 1, stdout=said or b"")


LEFT_BUILDER = (b'[{"ID": "srv-1", "Name": "fsl-build-fsl-edge", "Properties": {"fsl_image": "fsl-edge"},'
                b' "Networks": {"fsl-platform": ["10.20.0.9"]}},'
                b' {"ID": "srv-2", "Name": "fsl-build-mine", "Properties": {},'
                b' "Networks": {"fsl-platform": ["10.20.0.8"]}},'
                b' {"ID": "srv-3", "Name": "fsl-build-fsl-edge", "Properties": {"fsl_image": "fsl-edge"},'
                b' "Networks": {"other-platform": ["10.40.0.9"]}}]')


def test_down_removes_the_slot_then_the_fabric_then_the_stack():
    platform, cli = Platform(), Cli()

    command().take_down(platform, "fsl-platform", cli)

    assert platform.calls == [("DELETE", "/slot/"), ("DELETE", "/fabric/")]
    assert cli.ran[-1] == ["openstack", "stack", "delete", "--yes", "--wait", "fsl-platform"]


def test_down_removes_builders_first_because_their_ports_hold_the_platform_network():
    cli = Cli(servers=LEFT_BUILDER)

    command().take_down(Platform(), "fsl-platform", cli)

    assert cli.ran[-2:] == [["openstack", "server", "delete", "--wait", "srv-1"],
                            ["openstack", "stack", "delete", "--yes", "--wait", "fsl-platform"]], (
        "srv-2 is named like a builder but carries no fsl_image property, so it is not ours")


def test_only_builders_on_this_stack_s_network_are_removed():
    cli = Cli(servers=LEFT_BUILDER)

    assert command().rebuild.remove_builders("fsl-platform", cli) == ["srv-1"]

    assert ["openstack", "network", "show", "net-stack", "-f", "value", "-c", "name"] in cli.ran
    assert ["openstack", "stack", "resource", "show", "fsl-platform", "network",
            "-f", "value", "-c", "physical_resource_id"] in cli.ran


def test_a_stack_without_its_network_has_no_builders_to_remove():
    cli = Cli(servers=LEFT_BUILDER, network=None)

    assert command().rebuild.remove_builders("fsl-platform", cli) == []
    assert not [argv for argv in cli.ran if argv[1:3] in (["server", "list"], ["server", "delete"])]


def test_a_failed_stack_has_no_working_platform_so_up_rebuilds_it():
    cli = Cli(status=b"CREATE_FAILED")

    assert command().rebuild.working_address("fsl-platform", cli) is None
    assert not [argv for argv in cli.ran if argv[2] == "output"]


def test_a_failed_stack_is_taken_down_without_asking_its_platform(capsys):
    cli = Cli(servers=LEFT_BUILDER, status=b"DELETE_FAILED")

    command().take_down_broken("fsl-platform", "is DELETE_FAILED and has no platform to ask", cli)

    assert ["openstack", "server", "delete", "--wait", "srv-1"] in cli.ran
    assert cli.ran[-1][:3] == ["openstack", "stack", "delete"]
    assert "DELETE_FAILED" in capsys.readouterr().out


def test_a_working_stack_whose_address_cannot_be_read_is_not_taken_for_a_missing_one():
    cli = Cli(address=None)

    with pytest.raises(SystemExit, match="CREATE_COMPLETE but its address output cannot be read"):
        command().rebuild.working_address("fsl-platform", cli)


def test_a_stack_heat_is_still_working_on_is_left_alone():
    with pytest.raises(SystemExit, match="DELETE_IN_PROGRESS"):
        command().rebuild.working_address("fsl-platform", Cli(status=b"DELETE_IN_PROGRESS"))


def test_the_builder_marks_match_the_ones_the_platform_boots_with():
    from range import images

    module = command().rebuild
    assert (module.BUILDER, module.BUILDS) == (images.BUILDER, images.BUILDS)


def test_down_stops_before_the_stack_if_the_range_will_not_come_down():
    class Refusing(Platform):
        def __call__(self, verb, path):
            self.calls.append((verb, path))
            return 503, {"detail": "1 server port(s) still stand on fsl-mgmt"}

    ran = []
    with pytest.raises(SystemExit, match="still stand"):
        command().take_down(Refusing(), "fsl-platform", ran.append)
    assert not ran


def test_up_waits_until_every_slot_stands_and_every_slot_is_ready():
    platform = Platform(ready=[
        {"ready": False, "slot": {"phase": "READY"},
         "slots": [{"phase": "READY"}, {"phase": "NOT_STANDING"}]},
        {"ready": True, "slot": {"phase": "READY"}, "slots": [{"phase": "READY"}, {"phase": "CHECKING"}]},
        {"ready": True, "slot": {"phase": "READY"}, "slots": [{"phase": "READY"}, {"phase": "CHECKING"}]},
        {"ready": True, "slot": {"phase": "READY"}, "slots": [{"phase": "READY"}, {"phase": "READY"}]},
    ])

    converge(platform)

    gets = [i for i, call in enumerate(platform.calls) if call == ("GET", "/ready/")]
    assert len(gets) == 4, "a second slot still booting or checking is waited for, not skipped"
    assert platform.calls.index(("POST", "/configure/")) > gets[1] - 1


class StandingStack:
    def __init__(self, monkeypatch, holds, status="CREATE_COMPLETE"):
        self.module = command()
        self.calls = []
        rebuild = self.module.rebuild
        self.cli = Cli(servers=LEFT_BUILDER, status=status.encode())
        monkeypatch.setattr(rebuild, "load", lambda args: (
            type("Cloud", (), {"stack": "fsl-platform", "operator_key_file": "~/key", "range_key": "~/range",
                               "backups_keep": 1})(), {}))
        monkeypatch.setattr(rebuild, "run", self.cli)
        monkeypatch.setattr(rebuild, "stack_status", lambda stack: status)
        monkeypatch.setattr(rebuild, "address_of", lambda stack, run=None: "203.0.113.7")
        monkeypatch.setattr(rebuild, "holds_store", lambda old: holds)
        monkeypatch.setattr(rebuild, "start_platform", lambda old: self.calls.append("start"))
        monkeypatch.setattr(rebuild, "keep_range_key", lambda key, old: self.calls.append("key"))
        monkeypatch.setattr(rebuild, "back_up", lambda old, keep: self.calls.append("back_up"))
        monkeypatch.setattr(rebuild, "wait_for_api", lambda address: self.calls.append("api"))
        monkeypatch.setattr(self.module, "take_down", lambda call, stack, run: self.calls.append("take_down"))

    def down(self):
        self.module.down(self.module.arguments(["down"]))
        return self.calls


def test_down_on_a_platform_that_never_stored_anything_deletes_the_stack_without_a_backup(monkeypatch, capsys):
    stack = StandingStack(monkeypatch, holds=False)

    assert stack.down() == []

    assert ["openstack", "server", "delete", "--wait", "srv-1"] in stack.cli.ran
    assert stack.cli.ran[-1][:3] == ["openstack", "stack", "delete"]
    assert "nothing to back up" in capsys.readouterr().out


def test_down_on_a_platform_that_holds_a_store_backs_it_up_before_anything_is_deleted(monkeypatch):
    stack = StandingStack(monkeypatch, holds=True)

    assert stack.down() == ["start", "key", "back_up", "api", "take_down"], (
        "a store beside a stopped container is backed up through docker exec, so the container is "
        "started first, as up and up --replace do, and its API is waited for before the range is "
        "taken down through it")
    assert not [argv for argv in stack.cli.ran if argv[1:3] == ["stack", "delete"]]


def test_down_on_a_platform_whose_container_will_not_start_deletes_nothing(monkeypatch):
    stack = StandingStack(monkeypatch, holds=True)

    def stuck(old):
        raise SystemExit("the fsl-platform container on ubuntu@203.0.113.7 is not running and did not start")

    monkeypatch.setattr(stack.module.rebuild, "start_platform", stuck)
    with pytest.raises(SystemExit, match="did not start"):
        stack.down()
    assert stack.calls == []
    assert not [argv for argv in stack.cli.ran if argv[1:3] in (["stack", "delete"], ["server", "delete"])]


def test_down_on_a_platform_that_cannot_be_asked_deletes_nothing(monkeypatch):
    stack = StandingStack(monkeypatch, holds=False)

    def unreachable(old):
        raise SystemExit("cannot tell whether ubuntu@203.0.113.7 holds the platform's store")

    monkeypatch.setattr(stack.module.rebuild, "holds_store", unreachable)
    with pytest.raises(SystemExit, match="cannot tell"):
        stack.down()
    assert not [argv for argv in stack.cli.ran if argv[1:3] in (["stack", "delete"], ["server", "delete"])]


def test_down_on_a_working_stack_whose_address_cannot_be_read_deletes_nothing(monkeypatch):
    stack = StandingStack(monkeypatch, holds=True)
    monkeypatch.setattr(stack.module.rebuild, "address_of", lambda stack, run=None: None)

    with pytest.raises(SystemExit, match="cannot be read, so nothing was deleted"):
        stack.down()
    assert stack.calls == []
    assert not [argv for argv in stack.cli.ran if argv[1:3] in (["stack", "delete"], ["server", "delete"])]


def test_up_on_a_standing_stack_finishes_its_hand_over_and_replace_makes_a_new_vm(monkeypatch):
    module = command()
    rebuild = module.rebuild
    calls = []
    monkeypatch.setattr(rebuild, "load", lambda args: (object(), {}))
    monkeypatch.setattr(rebuild, "working_address", lambda stack: "203.0.113.7")
    monkeypatch.setattr(rebuild, "resume", lambda cloud, environment, address, sideload: calls.append("resume"))
    monkeypatch.setattr(rebuild, "rebuild", lambda cloud, environment, sideload: calls.append("rebuild")
                        or "203.0.113.8")
    monkeypatch.setattr(module, "converge", lambda call: calls.append("converge"))
    monkeypatch.setattr(module.os, "environ", {})
    cloud = type("Cloud", (), {"stack": "fsl-platform"})()
    monkeypatch.setattr(rebuild, "load", lambda args: (cloud, {}))

    module.up(module.arguments(["up"]))
    module.up(module.arguments(["up", "--replace"]))

    assert calls == ["resume", "converge", "rebuild", "converge"]
