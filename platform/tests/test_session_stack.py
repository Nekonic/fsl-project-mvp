import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from django.conf import settings

from api.models import Session
from range.declared import Declaration
from range.docker import Docker
from range.ports import RangeUnavailable

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.django_db


class Compose:
    def __init__(self, projects=(), working_dir="/opt/fsl", failing="", clock=None):
        self.calls = []
        self.timeouts = []
        self.clock = clock
        self.projects = [{"Name": name} for name in projects]
        self.working_dir = working_dir
        self.failing = failing

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("env") or {}))
        if argv[1] == "compose" and argv[2] != "ls":
            self.timeouts.append(kwargs.get("timeout"))
        if self.clock is not None:
            self.clock[0] += 100
        out, code = "", 0
        if argv[1:3] == ["compose", "ls"]:
            out = json.dumps(self.projects)
        elif argv[1] == "inspect":
            out = self.working_dir + "\n"
        elif self.failing and self.failing in argv:
            code = 1
        return type("Done", (), {"returncode": code, "stdout": out,
                                 "stderr": "dependency failed to start"})()

    def argvs(self):
        return [argv for argv, _ in self.calls]


def opened(compose, session_id=7):
    with patch("range.docker.subprocess.run", compose), \
            patch("range.docker.socket.gethostname", lambda: "c0ffee"):
        Docker(Declaration(), session_file="/src/session.yaml").open_session(session_id)


@pytest.mark.opens_session_stack
def test_a_session_brings_up_its_own_project_and_waits_until_it_is_healthy():
    compose = Compose()
    opened(compose)

    argv, env = compose.calls[-1]
    assert argv == [
        "docker", "compose", "-p", "fsl-7", "-f", "/src/session.yaml",
        "up", "-d", "--wait", "--no-build",
    ], (
        "without --wait the baseline is read from a target still starting, and "
        "without --no-build each session would build its own image"
    )
    assert env["FSL_HOST_DIR"] == "/opt/fsl", (
        "the stack's bind mounts resolve on the host, not inside the platform"
    )


@pytest.mark.opens_session_stack
def test_the_host_directory_is_read_from_the_platform_s_own_container():
    compose = Compose()
    opened(compose)

    [inspected] = [argv for argv in compose.argvs() if argv[1] == "inspect"]
    assert inspected[2] == "c0ffee"
    assert "com.docker.compose.project.working_dir" in inspected[-1]


@pytest.mark.opens_session_stack
def test_a_new_session_takes_down_the_stack_of_the_one_before():
    compose = Compose(projects=["fsl", "fsl-3", "fsl-30", "fsl-lab", "other"])
    opened(compose)

    downs = [argv for argv in compose.argvs() if "down" in argv]
    assert downs == [
        ["docker", "compose", "-p", "fsl-3", "down", "-v"],
        ["docker", "compose", "-p", "fsl-30", "down", "-v"],
    ], "the control plane or a project that is not a session was taken down"
    assert compose.argvs().index(downs[-1]) < len(compose.argvs()) - 1, (
        "the new stack came up before the old one went, and their pinned "
        "container names clash"
    )


@pytest.mark.opens_session_stack
def test_a_stack_that_does_not_come_up_is_an_outage():
    with pytest.raises(RangeUnavailable, match="dependency failed"):
        opened(Compose(failing="up"))


@pytest.mark.opens_session_stack
def test_a_platform_without_a_compose_working_dir_starts_nothing():
    compose = Compose(projects=["fsl-3"], working_dir="")

    with pytest.raises(RangeUnavailable, match="working_dir"):
        opened(compose)
    assert not [argv for argv in compose.argvs() if "up" in argv]
    assert not [argv for argv in compose.argvs() if "down" in argv], (
        "the previous session's stack was taken down although no new one "
        "could come up"
    )


@pytest.mark.opens_session_stack
def test_the_open_is_bounded_and_a_late_step_is_skipped():
    clock = [0.0]
    compose = Compose(projects=["fsl-3", "fsl-4", "fsl-5", "fsl-6"], clock=clock)

    with patch("range.docker.time.monotonic", lambda: clock[0]), \
            pytest.raises(RangeUnavailable, match="540 s"):
        opened(compose)

    assert compose.timeouts == [340.0, 240.0, 140.0, 40.0], (
        "a step was given the whole deadline, so the open can outlast the "
        "client waiting for it"
    )
    assert not [argv for argv in compose.argvs() if "up" in argv], (
        "the stack was brought up after the open had already spent its deadline"
    )


class Recording:
    def __init__(self, order, fails=False):
        self.order = order
        self.fails = fails

    def open_session(self, session_id):
        self.order.append(("open", session_id))
        if self.fails:
            raise RangeUnavailable("fsl-wg-board is unhealthy")

    def runner(self, role):
        return lambda *args, **kwargs: None


def test_the_baseline_is_taken_after_the_session_s_stack_is_up(client):
    order = []

    def ground_truth(wargame_id, host=""):
        order.append(("baseline", wargame_id))
        return [{"username": "admin", "password": "x"}]

    with patch("api.views.substrate", lambda: Recording(order)), \
            patch("api.views.loot.ground_truth", ground_truth):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 201, answer.content
    session_id = answer.json()["id"]
    assert order == [("open", session_id), ("baseline", "board")]
    assert Session.objects.get(pk=session_id).baseline == [
        {"username": "admin", "password": "x"}
    ]


def test_a_stack_that_did_not_come_up_leaves_no_open_session(client):
    order = []

    with patch("api.views.substrate", lambda: Recording(order, fails=True)):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 503, answer.content
    assert "unhealthy" in answer.json()["detail"]
    assert not Session.objects.filter(ended_at=None).exists(), (
        "a session whose target never came up stays open and is scored "
        "against nothing"
    )


def test_a_baseline_read_that_fails_after_the_row_exists_closes_it(client):
    def ground_truth(wargame_id, host=""):
        raise ValueError("board answered with something that is not JSON")

    with patch("api.views.substrate", lambda: Recording([])), \
            patch("api.views.loot.ground_truth", ground_truth), \
            pytest.raises(ValueError):
        client.post_json("/api/sessions/", {"scenario": "board"})

    assert Session.objects.exists()
    assert not Session.objects.filter(ended_at=None).exists(), (
        "a session whose baseline was never read stays open and blocks the "
        "next one with 409"
    )


def test_the_baseline_is_read_from_the_board_the_substrate_reports(client):
    asked = []

    class Addressed(Recording):
        def address(self, role):
            asked.append(role)
            return "10.20.0.7"

    def ground_truth(wargame_id, host=""):
        asked.append(host)
        return [{"username": "admin", "password": "x"}]

    with patch("api.views.substrate", lambda: Addressed([])), \
            patch("api.views.loot.ground_truth", ground_truth):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 201, answer.content
    assert asked == ["board", "10.20.0.7"], (
        "the baseline came from the board named in settings, not the board "
        "VM the red team attacks"
    )


def test_a_substrate_without_session_stacks_is_not_asked_for_one(client):
    class Shared:
        def runner(self, role):
            return lambda *args, **kwargs: None

    with patch("api.views.substrate", lambda: Shared()):
        answer = client.post_json("/api/sessions/", {"scenario": "board"})

    assert answer.status_code == 201, answer.content


def test_the_session_stack_has_the_shape_the_platform_opens_it_with():
    control = yaml.safe_load((ROOT / "compose.yaml").read_text())
    stack = yaml.safe_load((ROOT / "session.yaml").read_text())

    relative = [
        f"{name}: {entry}"
        for name, service in stack["services"].items()
        for entry in service.get("volumes") or []
        if entry.startswith(".")
    ]
    assert not relative, (
        f"{relative} resolve against the platform's own /src when the platform "
        f"opens the session, a path the Docker host does not have"
    )

    assert set(stack["networks"]) == set(control["networks"])
    assert all(
        entry == {"external": True, "name": f"fsl_{name}"}
        for name, entry in stack["networks"].items()
    ), stack["networks"]

    assert set(control["services"]) == {"platform", "elasticsearch", "kibana", "collector"}

    platform = control["services"]["platform"]
    mounted = {entry.split(":")[1]: entry.split(":")[0] for entry in platform["volumes"]}
    assert mounted.get(f"{platform['environment']['FSL_SOURCE']}/session.yaml") == "./session.yaml", (
        "the platform opens sessions from FSL_SOURCE/session.yaml and the "
        "host's file is not mounted there"
    )
    assert settings.FSL_SUBSTRATE_OPTIONS["session_file"].endswith("/session.yaml")

    assert re.search(r"cli-plugins/docker-compose\s", (ROOT / "platform/Dockerfile").read_text()), (
        "docker compose is a CLI plugin; without it every session open fails "
        "with 'compose is not a docker command'"
    )
