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
        self.commands.append(list(command))
        if self.raises is not None:
            raise self.raises
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

def test_a_role_with_no_host_is_a_clear_error(dispatch):
    fake = dispatch()
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable) as raised:
        substrate.run("forensics", ["true"])

    assert "forensics" in str(raised.value)
    assert seam.ATTACKER in str(raised.value)
    assert not fake.commands, (
        "an unfillable role reached the substrate, so the error would come "
        "back as whatever the substrate says about a missing host"
    )

def test_every_operation_refuses_a_role_with_no_host(dispatch):
    dispatch()
    substrate = seam.Docker()

    for call in (
        lambda: substrate.run("forensics", ["true"]),
        lambda: substrate.segments("forensics"),
        lambda: substrate.recreate("forensics"),
    ):
        with pytest.raises(seam.RangeUnavailable):
            call()

def finished(code, stderr=""):
    return f"{stderr}{seam.EXIT_MARK}{code}\n"

def test_a_command_that_ran_and_failed_is_a_result_not_an_outage(dispatch):
    dispatch(returncode=0, stdout="", stderr=finished(1, "nmap: not found"))
    substrate = seam.Docker()

    ran = substrate.run(seam.ATTACKER, ["sh", "-c", "command -v nmap"])

    assert not ran.ok
    assert ran.exit_code == 1
    assert "not found" in ran.stderr

def test_a_command_that_ran_and_passed_keeps_its_two_streams_apart(dispatch):
    dispatch(returncode=0, stdout="5.188.10.4 \n", stderr=finished(0, "warning"))
    substrate = seam.Docker()

    ran = substrate.run(seam.ATTACKER, ["sh", "-c", "hostname -I"])

    assert ran.ok
    assert ran.stdout.split() == ["5.188.10.4"]
    assert ran.stderr == "warning"
    assert ran.output == "5.188.10.4 \nwarning"

def test_a_command_that_could_not_be_dispatched_is_not_a_failed_command(dispatch):
    dispatch(raises=FileNotFoundError("docker"))
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.run(seam.ATTACKER, ["true"])

def test_a_host_that_is_not_running_is_not_a_failed_command(dispatch):
    dispatch(returncode=1, stderr="Error: No such container: fsl-kali")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable) as raised:
        substrate.run(seam.ATTACKER, ["true"])

    assert seam.ATTACKER in str(raised.value)

def test_a_command_that_never_finished_is_not_a_failed_command(dispatch):
    dispatch(raises=subprocess.TimeoutExpired(cmd="docker", timeout=8))
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.run(seam.ATTACKER, ["sleep", "99"])

def test_a_command_is_dispatched_to_the_host_filling_the_role(dispatch):
    fake = dispatch(stderr=finished(0))
    substrate = seam.Docker()

    substrate.run(seam.SENSOR, ["tail", "-5", "/var/log/suricata/eve.json"])

    assert fake.commands == [[
        "docker", "exec", "fsl-suricata",
        *seam.through_shell(["tail", "-5", "/var/log/suricata/eve.json"]),
    ]]

def test_a_daemon_that_cannot_be_reached_is_not_a_failed_command(dispatch):
    dispatch(returncode=1, stderr=(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
        "Is the docker daemon running?\n"
    ))
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable) as raised:
        substrate.run(seam.ATTACKER, ["curl", "http://juice-shop:3000/"])

    assert seam.ATTACKER in str(raised.value), raised.value
    assert "Cannot connect" in str(raised.value), (
        "docker's own exit status of 1 was taken for the command's, so an "
        "assertion that the attacker cannot reach the target passed with no "
        "daemon to run anything"
    )

def test_the_exit_status_is_the_one_the_host_reported(dispatch):
    dispatch(returncode=0, stdout="", stderr=finished(127, "sh: 1: nmap: not found\n"))
    substrate = seam.Docker()

    ran = substrate.run(seam.ATTACKER, ["nmap", "--version"])

    assert (ran.exit_code, ran.stderr) == (127, "sh: 1: nmap: not found\n")

def test_the_target_has_no_shell_and_reports_through_its_node(dispatch):
    fake = dispatch(stdout="200\n", stderr=finished(0))
    substrate = seam.Docker()

    ran = substrate.run(seam.TARGET, ["/nodejs/bin/node", "-e", "1"])

    assert fake.commands[0][:4] == ["docker", "exec", "fsl-juice-shop", "/nodejs/bin/node"], (
        "the target is a distroless image: a command wrapped in sh would fail "
        "there before it ran"
    )
    assert (ran.exit_code, ran.stdout) == (0, "200\n")

def run_here(wrapped, interpreter):
    done = subprocess.run(
        [interpreter, *wrapped[1:]], capture_output=True, text=True, timeout=30,
    )
    return done.stdout, seam.reported(done.stderr)

@pytest.mark.parametrize("through, interpreter", [
    ("through_shell", "/bin/sh"), ("through_node", None),
])
def test_the_report_survives_a_real_interpreter(through, interpreter):
    wrap = getattr(seam, through)
    interpreter = interpreter or node()

    said, status = run_here(
        wrap([node(), "-e", "console.log('200'); console.error('warn'); process.exit(4)"]),
        interpreter,
    )
    assert said == "200\n"
    assert status == (4, "warn\n")

    _, missing = run_here(wrap(["/nonexistent/fsl-tool", "--flag"]), interpreter)
    assert missing is not None and missing[0] == 127, missing

def test_the_segments_a_role_sits_on_come_back_as_names(dispatch):
    dispatch(stdout=json.dumps({"fsl_edge": {}, "fsl_estate": {}}))
    substrate = seam.Docker()

    assert substrate.segments(seam.GATEWAY) == frozenset({"fsl_edge", "fsl_estate"})

def test_two_roles_sharing_no_segment_is_an_answer_not_an_outage(dispatch):
    dispatch(stdout=json.dumps({"fsl_edge": {}}))
    substrate = seam.Docker()
    attacker = substrate.segments(seam.ATTACKER)
    dispatch(stdout=json.dumps({"fsl_estate": {}}))
    target = substrate.segments(seam.TARGET)

    assert (attacker, target) == (frozenset({"fsl_edge"}), frozenset({"fsl_estate"}))
    assert not attacker & target

def test_segments_of_a_host_that_is_not_there_is_an_outage(dispatch):
    dispatch(returncode=1, stderr="Error: No such object: fsl-juice-shop")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.segments(seam.TARGET)

def test_a_segment_list_that_is_not_a_list_is_an_outage(dispatch):
    dispatch(returncode=0, stdout="<null>")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.segments(seam.TARGET)

def test_recreating_a_role_takes_the_host_away_and_brings_it_back(dispatch):
    fake = dispatch()
    substrate = seam.Docker()

    substrate.recreate(seam.TARGET)

    assert fake.commands == [
        ["docker", "compose", "rm", "-sf", "juice-shop"],
        ["docker", "compose", "up", "-d", "juice-shop"],
    ]

def test_a_recreate_that_did_not_take_the_host_away_does_not_bring_it_back(dispatch):
    fake = dispatch(returncode=1, stderr="no configuration file provided")
    substrate = seam.Docker()

    with pytest.raises(seam.RangeUnavailable):
        substrate.recreate(seam.TARGET)

    assert len(fake.commands) == 1, (
        "the host was never removed and the seam reported it recreated anyway"
    )

def test_the_roles_are_named_by_what_they_do_in_the_exercise():
    for role in seam.ROLES:
        assert "fsl" not in role and "docker" not in role, role
        assert role in seam.DOCKER_HOSTS

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
