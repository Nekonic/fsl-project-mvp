import importlib.util
import io
import itertools
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/cloud"


def command():
    loader = SourceFileLoader("cr_cloud_command", str(COMMAND))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("cr_cloud_command", loader))
    loader.exec_module(module)
    return module


def slots(*states):
    return {"slots": [{"slot": number, "refill": {"state": state, "reason": "the stack failed" if state == "failed"
                                                  else ""}} for number, state in enumerate(states, start=1)]}


class Platform:
    def __init__(self, fabric=None, refills=None, removed=(), standing=()):
        self.calls = []
        self.standing = iter(standing)
        self.removed = list(removed)
        self.fabric = fabric or (200, {"present": [], "clean": True})
        self.refills = iter(refills or [slots("running", "running"), slots("idle", "running"), slots("idle", "idle")])

    def __call__(self, verb, path):
        self.calls.append((verb, path))
        if (verb, path) == ("POST", "/fabric/"):
            return self.fabric
        if (verb, path) == ("POST", "/pool/"):
            return 200, slots("running", "running")
        if (verb, path) == ("GET", "/"):
            return 200, next(self.refills)
        if (verb, path) == ("GET", "/pool/"):
            return 200, {"slots": [{"slot": 1, "servers": servers} for servers in [next(self.standing, [])]]}
        return 200, {"removed": self.removed}


def converge(platform):
    clock = itertools.count()
    return command().converge(platform, sleep=lambda seconds: None, clock=lambda: next(clock))


def test_up_builds_the_fabric_then_fills_the_pool_and_waits_until_every_slot_is_built_and_set_up():
    platform = Platform()

    assert [slot["refill"]["state"] for slot in converge(platform)] == ["idle", "idle"]

    assert [call for call in platform.calls if call[0] == "POST"] == [("POST", "/fabric/"), ("POST", "/pool/")]
    assert platform.calls.count(("GET", "/")) == 3, "a second slot still building is waited for, not skipped"


def test_what_an_earlier_range_left_is_removed_before_the_pool_is_filled(capsys):
    platform = Platform(removed=[{"kind": "server", "id": "srv-cr-range"}])

    converge(platform)

    assert platform.calls[:3] == [("POST", "/fabric/"), ("DELETE", "/leftovers/"), ("POST", "/pool/")], (
        "the old range host holds 6 vCPU and 16 GB of the quota the pool's slot VMs need")
    assert "server srv-cr-range" in capsys.readouterr().out


def test_a_drifted_fabric_stops_up_before_any_slot_boots():
    platform = Platform(fabric=(503, {"errors": [{"path": "", "code": "range_drifted"}]}))

    with pytest.raises(SystemExit, match="range_drifted"):
        converge(platform)
    assert platform.calls == [("POST", "/fabric/")]


def test_a_slot_that_failed_to_build_stops_up_with_its_reason():
    with pytest.raises(SystemExit, match="slot 2: the stack failed"):
        converge(Platform(refills=[slots("idle", "failed")]))


def test_up_and_down_call_only_range_operations_the_schema_has():
    from bots import tools

    module = command()
    entries = tools.operation_entries(tools.contract())

    assert {path for _, path in module.RANGE_CALLS} == {"/", "/fabric/", "/leftovers/", "/pool/"}
    assert all(entries[name][:2] == (verb.lower(), f"/api/staff/range{path}")
               for (verb, path), name in module.RANGE_CALLS.items())


class Cli:
    def __init__(self, servers=b"[]", status=b"CREATE_COMPLETE", address=b"203.0.113.7",
                 network=b"net-stack", stacks=b""):
        self.ran = []
        self.answers = {"list": servers, "show": status, "output": address, "resource": network}
        self.stacks = stacks

    def __call__(self, argv, stdin=None, check=True):
        self.ran.append(argv)
        if argv[1:3] == ["stack", "list"]:
            return subprocess.CompletedProcess(argv, 0, stdout=self.stacks)
        if argv[1:3] == ["network", "show"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"cr-platform\n")
        said = self.answers.get(argv[2], b"")
        return subprocess.CompletedProcess(argv, 0 if said is not None else 1, stdout=said or b"")


LEFT_BUILDER = (b'[{"ID": "srv-1", "Name": "cr-build-cr-edge", "Properties": {"cr_image": "cr-edge"},'
                b' "Networks": {"cr-platform": ["10.20.0.9"]}},'
                b' {"ID": "srv-2", "Name": "cr-build-mine", "Properties": {},'
                b' "Networks": {"cr-platform": ["10.20.0.8"]}},'
                b' {"ID": "srv-3", "Name": "cr-build-cr-edge", "Properties": {"cr_image": "cr-edge"},'
                b' "Networks": {"other-platform": ["10.40.0.9"]}}]')


def take_down(platform, cli):
    clock = itertools.count()
    command().take_down(platform, "cr-platform", cli, sleep=lambda seconds: None, clock=lambda: next(clock))


def test_down_deletes_the_slot_stacks_waits_for_them_then_removes_the_fabric_then_the_stack():
    platform, cli = Platform(standing=[[{"host": "cr-slot-1", "status": "DELETING"}]]), Cli()

    take_down(platform, cli)

    assert platform.calls == [("DELETE", "/pool/"), ("GET", "/pool/"), ("GET", "/pool/"), ("DELETE", "/fabric/")], (
        "a slot VM's control port stands on cr-mgmt until Heat has deleted its stack")
    assert cli.ran[-1] == ["openstack", "stack", "delete", "--yes", "--wait", "cr-platform"]


def test_down_removes_builders_first_because_their_ports_hold_the_platform_network():
    cli = Cli(servers=LEFT_BUILDER)

    take_down(Platform(), cli)

    assert cli.ran[-2:] == [["openstack", "server", "delete", "--wait", "srv-1"],
                            ["openstack", "stack", "delete", "--yes", "--wait", "cr-platform"]], (
        "srv-2 is named like a builder but carries no cr_image property, so it is not ours")


def test_only_builders_on_this_stack_s_network_are_removed():
    cli = Cli(servers=LEFT_BUILDER)

    assert command().rebuild.remove_builders("cr-platform", cli) == ["srv-1"]

    assert ["openstack", "network", "show", "net-stack", "-f", "value", "-c", "name"] in cli.ran
    assert ["openstack", "stack", "resource", "show", "cr-platform", "network",
            "-f", "value", "-c", "physical_resource_id"] in cli.ran


def test_a_stack_without_its_network_has_no_builders_to_remove():
    cli = Cli(servers=LEFT_BUILDER, network=None)

    assert command().rebuild.remove_builders("cr-platform", cli) == []
    assert not [argv for argv in cli.ran if argv[1:3] in (["server", "list"], ["server", "delete"])]


class HeldNetwork(Cli):
    PORTS = (b'[{"ID": "port-router", "Device Owner": "network:router_interface"},'
             b' {"ID": "port-platform", "Device Owner": "compute:nova"},'
             b' {"ID": "port-dev", "Device Owner": "compute:nova"}]')
    DEVICES = {"port-platform": b"srv-platform\n", "port-dev": b"srv-dev\n"}

    def __call__(self, argv, stdin=None, check=True):
        if argv[1:3] == ["port", "list"]:
            self.ran.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=self.PORTS)
        if argv[1:3] == ["port", "show"]:
            self.ran.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=self.DEVICES[argv[3]])
        if argv[1:3] == ["server", "show"]:
            self.ran.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=b"cr-dev\n")
        if argv[1:4] == ["stack", "resource", "show"] and argv[5] == "server":
            self.ran.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=b"srv-platform\n")
        return super().__call__(argv, stdin, check)


def test_a_server_of_someone_else_on_the_stack_s_network_stops_the_delete_before_anything_is_deleted():
    cli = HeldNetwork()

    with pytest.raises(SystemExit, match="cr-dev has a port on stack cr-platform's network"):
        command().rebuild.delete_stack("cr-platform", cli)

    assert not [argv for argv in cli.ran if "delete" in argv], (
        "a floating IP on that server keeps the router interface, so Heat would fail halfway")


def test_only_the_stack_s_own_server_on_its_network_lets_the_delete_go_on():
    class OwnOnly(HeldNetwork):
        PORTS = b'[{"ID": "port-platform", "Device Owner": "compute:nova"}]'

    cli = OwnOnly()

    command().rebuild.delete_stack("cr-platform", cli)

    assert cli.ran[-1] == ["openstack", "stack", "delete", "--yes", "--wait", "cr-platform"]


def test_a_failed_stack_has_no_working_platform_so_up_rebuilds_it():
    cli = Cli(status=b"CREATE_FAILED")

    assert command().rebuild.working_address("cr-platform", cli) is None
    assert not [argv for argv in cli.ran if argv[2] == "output"]


def test_a_failed_stack_is_taken_down_without_asking_its_platform_and_its_slot_stacks_with_it(capsys):
    cli = Cli(servers=LEFT_BUILDER, status=b"DELETE_FAILED", stacks=b"stack-1\nstack-4\n")

    command().take_down_broken("cr-platform", "is DELETE_FAILED and has no platform to ask", cli)

    assert ["openstack", "stack", "list", "--tags", "cr-range", "-f", "value", "-c", "ID"] in cli.ran
    assert ["openstack", "stack", "delete", "--yes", "--wait", "stack-1", "stack-4"] in cli.ran
    assert ["openstack", "server", "delete", "--wait", "srv-1"] in cli.ran
    assert cli.ran[-1][:3] == ["openstack", "stack", "delete"]
    assert "DELETE_FAILED" in capsys.readouterr().out


def test_a_working_stack_whose_address_cannot_be_read_is_not_taken_for_a_missing_one():
    cli = Cli(address=None)

    with pytest.raises(SystemExit, match="CREATE_COMPLETE but its address output cannot be read"):
        command().rebuild.working_address("cr-platform", cli)


def test_a_stack_heat_is_still_working_on_is_left_alone():
    with pytest.raises(SystemExit, match="DELETE_IN_PROGRESS"):
        command().rebuild.working_address("cr-platform", Cli(status=b"DELETE_IN_PROGRESS"))


def test_down_stops_before_the_stack_if_the_range_will_not_come_down():
    class Refusing(Platform):
        def __call__(self, verb, path):
            self.calls.append((verb, path))
            return 503, {"errors": [{"path": "", "code": "range_unavailable"}]}

    ran = []
    with pytest.raises(SystemExit, match="range_unavailable"):
        command().take_down(Refusing(), "cr-platform", ran.append)
    assert not ran


class StandingStack:
    def __init__(self, monkeypatch, holds, status="CREATE_COMPLETE"):
        self.module = command()
        self.calls = []
        rebuild = self.module.rebuild
        self.cli = Cli(servers=LEFT_BUILDER, status=status.encode())
        monkeypatch.setattr(rebuild, "load", lambda args: (
            type("Cloud", (), {"stack": "cr-platform", "key_file": "~/key", "range_key": "~/range",
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
        raise SystemExit("the cr-platform container on ubuntu@203.0.113.7 is not running and did not start")

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
    cloud = type("Cloud", (), {"stack": "cr-platform"})()
    monkeypatch.setattr(rebuild, "load", lambda args: (cloud, {}))

    module.up(module.arguments(["up"]))
    module.up(module.arguments(["up", "--replace"]))

    assert calls == ["resume", "converge", "rebuild", "converge"]


def test_every_line_up_prints_starts_with_the_time_it_was_printed():
    written = io.StringIO()
    stamped = command().Stamped(written, now=lambda: (2026, 11, 17, 9, 5, 7, 0, 321, 0))

    print("slot standing", file=stamped)
    stamped.write("configure: 503\ntrying ")
    stamped.write("again\n")

    assert written.getvalue() == "09:05:07 slot standing\n09:05:07 configure: 503\n09:05:07 trying again\n"
