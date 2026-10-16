import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests.browser import node

REPO_ROOT = Path(__file__).resolve().parents[2]
SEAM_PATH = REPO_ROOT / "test" / "range.py"

def _load_seam():
    spec = importlib.util.spec_from_file_location("acceptance_range", SEAM_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

seam = _load_seam()

class Dispatched:

    def __init__(self, returncode=0, stdout="", stderr="", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.commands = []
        self.looked_up = []

    def __call__(self, command, **kwargs):
        if self.raises is not None:
            raise self.raises
        if command[1] == "ps":
            self.looked_up.append(list(command))
            service = command[3].rpartition("=")[2]
            return types.SimpleNamespace(
                returncode=0, stderr="",
                stdout=f"fsl-3-{service}-1 fsl-3\nfsl-7-{service}-1 fsl-7\nfsl-{service} fsl\n",
            )
        self.commands.append(list(command))
        return types.SimpleNamespace(
            returncode=self.returncode, stdout=self.stdout, stderr=self.stderr
        )

@pytest.fixture
def dispatch(monkeypatch):

    def install(**kwargs):
        fake = Dispatched(**kwargs)
        monkeypatch.setattr(
            seam,
            "subprocess",
            types.SimpleNamespace(
                run=fake, SubprocessError=subprocess.SubprocessError,
                TimeoutExpired=subprocess.TimeoutExpired,
            ),
        )
        return fake

    return install

def finished(code, stderr=""):
    return f"{stderr}{seam.EXIT_MARK}{code}\n"

def test_a_command_that_ran_and_failed_is_a_result_not_an_outage(dispatch):
    dispatch(returncode=0, stdout="", stderr=finished(1, "nmap: not found"))
    substrate = seam.Docker()

    ran = substrate.run(seam.ATTACKER, ["sh", "-c", "command -v nmap"])

    assert not ran.ok
    assert ran.exit_code == 1
    assert "not found" in ran.stderr

def test_a_command_reaches_the_session_it_names_and_otherwise_the_newest(dispatch):
    fake = dispatch(stderr=finished(0))

    seam.Docker().run(seam.ATTACKER, ["true"], session=3)
    seam.Docker().run(seam.SENSOR, ["true"])

    assert fake.commands[0][:3] == ["docker", "exec", "fsl-3-kali-1"]
    assert fake.looked_up[0][2:4] == ["--filter", "label=com.docker.compose.service=kali"]
    assert fake.commands[1][:3] == ["docker", "exec", "fsl-7-suricata-1"]

@pytest.mark.parametrize("failure", [
    {"returncode": 1, "stderr": "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                                "Is the docker daemon running?\n"},
    {"returncode": 1, "stderr": "Error: No such container: fsl-kali"},
    {"raises": FileNotFoundError("docker")},
    {"raises": subprocess.TimeoutExpired(cmd="docker", timeout=8)},
], ids=["daemon-down", "host-not-running", "not-dispatched", "never-finished"])
def test_a_command_the_substrate_could_not_run_is_an_outage_not_a_failed_command(dispatch, failure):
    dispatch(**failure)

    with pytest.raises(seam.RangeUnavailable):
        seam.Docker().run(seam.ATTACKER, ["curl", "http://board.com/"])

def run_here(wrapped, interpreter):
    done = subprocess.run(
        [interpreter, *wrapped[1:]], capture_output=True, text=True, timeout=30,
    )
    return done.stdout, seam.reported(done.stderr)

def test_the_report_survives_a_real_interpreter():
    said, status = run_here(
        seam.through_shell(
            [node(), "-e", "console.log('200'); console.error('warn'); process.exit(4)"]
        ),
        "/bin/sh",
    )
    assert said == "200\n"
    assert status == (4, "warn\n")

    _, missing = run_here(seam.through_shell(["/nonexistent/fsl-tool", "--flag"]), "/bin/sh")
    assert missing is not None and missing[0] == 127, missing

def test_two_roles_sharing_no_segment_is_an_answer_not_an_outage(dispatch):
    dispatch(stdout=json.dumps({"fsl_edge": {}}))
    substrate = seam.Docker()
    attacker = substrate.segments(seam.ATTACKER)
    dispatch(stdout=json.dumps({"fsl_estate": {}}))
    target = substrate.segments(seam.BOARD)

    assert (attacker, target) == (frozenset({"fsl_edge"}), frozenset({"fsl_estate"}))
    assert not attacker & target

@pytest.mark.parametrize("failure", [
    {"returncode": 1, "stderr": "Error: No such object: fsl-wg-board"},
    {"returncode": 0, "stdout": "<null>"},
], ids=["host-missing", "not-a-list"])
def test_segments_the_substrate_could_not_list_are_an_outage(dispatch, failure):
    dispatch(**failure)

    with pytest.raises(seam.RangeUnavailable):
        seam.Docker().segments(seam.BOARD)

def test_a_host_no_session_stack_holds_is_not_recreated_into_a_guessed_one(dispatch):
    fake = dispatch(stdout="\n")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable, match="no session stack"):
        substrate.recreate(seam.BOARD)

    assert len(fake.commands) == 1, (
        "compose ran without the project of the open session, so it would "
        "start a stack nobody opened"
    )

def test_a_recreate_that_did_not_take_the_host_away_does_not_bring_it_back(dispatch):
    fake = dispatch(returncode=1, stderr="no configuration file provided")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.recreate(seam.BOARD)

    assert len(fake.commands) == 1, (
        "the host was never removed and the seam reported it recreated anyway"
    )

def test_nothing_substrate_specific_crosses_the_seam():
    source = SEAM_PATH.read_text()
    signatures = [
        line for line in source.splitlines()
        if line.lstrip().startswith("def ") or line.lstrip().startswith("class ")
    ]

    for line in signatures:
        assert "docker" not in line.lower() or line.lstrip().startswith("class Docker"), (
            f"the substrate is named in a signature the tests call: {line.strip()}"
        )

def test_the_seam_does_not_need_the_platform_to_run():
    source = SEAM_PATH.read_text()

    assert "django" not in source.lower(), (
        "the acceptance suite reaches the range over the substrate and the "
        "platform over HTTP; importing Django would make it a unit test"
    )
    assert "import range" not in source, (
        "the seam must not borrow platform/range/, which is only importable "
        "with platform/ as the working directory"
    )
