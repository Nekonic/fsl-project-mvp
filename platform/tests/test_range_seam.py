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

    def __call__(self, command, **kwargs):
        if self.raises is not None:
            raise self.raises
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

def answered(code, stdout="", stderr=""):
    output = f"{stdout}\n{seam.STDOUT_END}\n{stderr}"
    return f"{seam.PLATFORM_ANSWER}{json.dumps({'exit_code': code, 'output': output})}\n"

@pytest.mark.parametrize("role, said", [
    (seam.ATTACKER, {"stdout": answered(1, stderr="nmap: not found")}),
    (seam.SCORER, {"stderr": finished(1, "nmap: not found")}),
], ids=["through-the-platform", "on-the-platform"])
def test_a_command_that_ran_and_failed_is_a_result_not_an_outage(dispatch, role, said):
    dispatch(returncode=0, **said)

    ran = seam.ThroughPlatform().run(role, ["sh", "-c", "command -v nmap"])

    assert not ran.ok
    assert ran.exit_code == 1
    assert "not found" in ran.stderr

def test_a_command_names_to_the_platform_the_session_it_was_given_and_no_other(dispatch):
    fake = dispatch(stdout=answered(0))

    seam.ThroughPlatform().run(seam.ATTACKER, ["true"], session=3)
    seam.ThroughPlatform().run(seam.SENSOR, ["true"])

    platform = seam.declared_roles()[seam.SCORER]
    assert fake.commands[0][:6] == ["docker", "exec", platform, "python", "manage.py", "run_on_role"]
    assert fake.commands[0][6] == seam.ATTACKER and fake.commands[0][-2:] == ["--session", "3"]
    assert fake.commands[1][6] == seam.SENSOR and "--session" not in fake.commands[1]

@pytest.mark.parametrize("role", [seam.ATTACKER, seam.SCORER], ids=["through-the-platform", "on-the-platform"])
@pytest.mark.parametrize("failure", [
    {"returncode": 1, "stderr": "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                                "Is the docker daemon running?\n"},
    {"returncode": 1, "stderr": "Error: No such container: fsl-platform"},
    {"returncode": 0, "stdout": "", "stderr": ""},
    {"raises": FileNotFoundError("docker")},
    {"raises": subprocess.TimeoutExpired(cmd="docker", timeout=8)},
], ids=["daemon-down", "platform-not-running", "no-answer", "not-dispatched", "never-finished"])
def test_a_command_the_platform_could_not_run_is_an_outage_not_a_failed_command(dispatch, role, failure):
    dispatch(**failure)

    with pytest.raises(seam.RangeUnavailable):
        seam.ThroughPlatform().run(role, ["curl", "http://board.com/"])

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

def test_nothing_substrate_specific_crosses_the_seam():
    source = SEAM_PATH.read_text()
    signatures = [
        line for line in source.splitlines()
        if line.lstrip().startswith("def ") or line.lstrip().startswith("class ")
    ]

    for line in signatures:
        assert "docker" not in line.lower(), (
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
