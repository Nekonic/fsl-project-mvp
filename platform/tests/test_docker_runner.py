import stat

import pytest

from range import declared, docker
from range.ports import RangeUnavailable

pytestmark = pytest.mark.stands_in_for_docker


@pytest.fixture
def docker_that(tmp_path, monkeypatch):
    def install(script: str):
        stand_in = tmp_path / "docker"
        stand_in.write_text("#!/bin/sh\n" + FINDS_THE_SESSION + script)
        stand_in.chmod(stand_in.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        return docker.Docker(declared=declared.read(), project="fsl")

    return install


FINDS_THE_SESSION = (
    '[ "$1" = ps ] && { echo "fsl-1-suricata-1 fsl-1"; exit 0; }\n'
    '[ "$1" = inspect ] && { echo \'{"fsl_edge": {"IPAddress": "5.188.10.4"}}\'; exit 0; }\n'
)

RUNS_WHAT_IT_IS_GIVEN = (
    'shift\n[ "$1" = -i ] && shift\nshift\nexec "$@"\n'
)


def test_output_that_is_not_utf8_does_not_crash_the_runner(docker_that):
    substrate = docker_that(RUNS_WHAT_IT_IS_GIVEN)

    ran = substrate.runner("sensor")(["printf", "a\\377b"])

    assert ran.output == "a\ufffdb", (
        f"a log the red team can write to is read back through this runner, "
        f"and one byte that is not UTF-8 raised UnicodeDecodeError - neither "
        f"Ran nor RangeUnavailable, so no caller handled it: {ran}"
    )


@pytest.mark.parametrize("script, call", [
    ("sleep 5\n", lambda substrate: substrate.runner("sensor")(["true"], timeout=0.2)),
    ('case "$1" in network) echo fsl_edge fsl edge ;; *) sleep 5 ;; esac\n',
     lambda substrate: substrate.launcher("edge")("fsl-kali", ["sqlmap"], timeout=0.2)),
], ids=["runner", "launcher"])
def test_a_command_that_outlives_its_timeout_is_named_as_such(docker_that, script, call):
    with pytest.raises(RangeUnavailable, match="did not finish within"):
        call(docker_that(script))


def test_a_command_that_fails_is_a_command_that_ran(docker_that):
    ran = docker_that(RUNS_WHAT_IT_IS_GIVEN).runner("sensor")(
        ["sh", "-c", "echo no such file >&2; exit 1"]
    )

    assert (ran.exit_code, ran.output) == (1, "no such file\n"), ran


@pytest.mark.parametrize("said, named", [
    ("Error response from daemon: container 92e9bf6c is not running", "is not running"),
    ("Cannot connect to the Docker daemon at unix:///x/docker.sock. Is the docker daemon running?",
     "Cannot connect"),
], ids=["container-stopped", "daemon-gone"])
def test_a_docker_that_cannot_run_the_command_is_unavailable_not_a_failed_command(docker_that, said, named):
    substrate = docker_that(f"echo '{said}' >&2\nexit 1\n")

    with pytest.raises(RangeUnavailable, match=named):
        substrate.runner("sensor")(["cat", "/etc/suricata/rules/local.rules"])
