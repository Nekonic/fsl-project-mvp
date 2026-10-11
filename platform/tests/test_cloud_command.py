import importlib.util
import itertools
import subprocess
import sys
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


def test_images_are_asked_for_until_they_are_clean():
    platform = Platform(images=[
        {"images": [image("building")], "leftovers": [], "clean": False},
        {"images": [image("building")], "leftovers": [], "clean": False},
        {"images": [image("ready")], "leftovers": [], "clean": True},
    ])

    converge(platform)

    assert platform.calls.count(("POST", "/images/")) == 3


def test_a_failed_image_stops_up_with_why():
    platform = Platform(images=[{"images": [image("failed", detail="checksum did NOT match")],
                                 "leftovers": [], "clean": False}])

    with pytest.raises(SystemExit, match="checksum did NOT match"):
        converge(platform)
    assert ("POST", "/slot/") not in platform.calls


def test_an_image_nothing_can_build_stops_up():
    platform = Platform(images=[{"images": [image("missing", bundle="")], "leftovers": [], "clean": False}])

    with pytest.raises(SystemExit, match="no script builds it"):
        converge(platform)


def test_leftovers_beside_ready_images_are_cleaned_so_up_can_finish():
    platform = Platform(images=[
        {"images": [image("ready")], "leftovers": [{"kind": "server", "id": "s"}], "clean": False},
        {"images": [image("ready")], "leftovers": [], "clean": True},
    ])

    converge(platform)

    assert ("DELETE", "/images/") in platform.calls


def test_a_drifted_fabric_stops_up_before_any_image_is_built():
    platform = Platform(fabric={"drifted": ["keypair fsl-platform holds another public key"]})

    with pytest.raises(SystemExit, match="another public key"):
        converge(platform)
    assert platform.calls == [("POST", "/fabric/")]


def test_configure_is_retried_while_the_vms_ssh_is_not_up_yet():
    platform = Platform(configure=[(503, {"detail": "fsl-edge never reported the command finishing"}),
                                   (200, {"configured": []})])

    converge(platform)

    assert platform.calls.count(("POST", "/configure/")) == 2


def test_a_configuration_the_edge_refused_stops_up():
    platform = Platform(configure=[(409, {"detail": "fsl-edge did not take its configuration"})])

    with pytest.raises(SystemExit, match="did not take its configuration"):
        converge(platform)


def test_down_removes_the_slot_then_the_fabric_then_the_stack():
    platform, ran = Platform(), []

    command().take_down(platform, "fsl-platform", ran.append)

    assert platform.calls == [("DELETE", "/slot/"), ("DELETE", "/fabric/")]
    assert ran == [["openstack", "stack", "delete", "--yes", "--wait", "fsl-platform"]]


def test_down_stops_before_the_stack_if_the_range_will_not_come_down():
    class Refusing(Platform):
        def __call__(self, verb, path):
            self.calls.append((verb, path))
            return 503, {"detail": "1 server port(s) still stand on fsl-mgmt"}

    ran = []
    with pytest.raises(SystemExit, match="still stand"):
        command().take_down(Refusing(), "fsl-platform", ran.append)
    assert not ran


@pytest.mark.parametrize("action", ["up", "down"])
def test_without_cloud_yaml_it_refuses_and_says_what_to_copy(tmp_path, action):
    done = subprocess.run([sys.executable, str(COMMAND), action, "--cloud", str(tmp_path / "cloud.yaml")],
                          capture_output=True, text=True)

    assert done.returncode != 0
    assert "cloud.example.yaml" in done.stderr and "Traceback" not in done.stderr
