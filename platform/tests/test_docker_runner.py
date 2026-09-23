import stat

import pytest

from range import declared, docker
from range.ports import RangeUnavailable

pytestmark = pytest.mark.stands_in_for_docker


@pytest.fixture
def docker_that(tmp_path, monkeypatch):
    def install(script: str):
        stand_in = tmp_path / "docker"
        stand_in.write_text("#!/bin/sh\n" + script)
        stand_in.chmod(stand_in.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        return docker.Docker(declared=declared.read(), project="fsl")

    return install


RUNS_WHAT_IT_IS_GIVEN = (
    'shift\n[ "$1" = -i ] && shift\nshift\nexec "$@"\n'
)


def test_output_that_is_not_utf8_does_not_crash_the_runner(docker_that):
    substrate = docker_that(RUNS_WHAT_IT_IS_GIVEN)

    ran = substrate.runner("wiki")(["printf", "a\\377b"])

    assert ran.output == "a\ufffdb", (
        f"a log the red team can write to is read back through this runner, "
        f"and one byte that is not UTF-8 raised UnicodeDecodeError - neither "
        f"Ran nor RangeUnavailable, so no caller handled it: {ran}"
    )


def test_a_command_that_outlives_its_timeout_is_named_as_such(docker_that):
    substrate = docker_that("sleep 5\n")

    with pytest.raises(RangeUnavailable, match="did not finish within 1s"):
        substrate.runner("wiki")(["true"], timeout=1)


def test_a_tool_that_outlives_its_timeout_is_named_as_such(docker_that):
    substrate = docker_that(
        'case "$1" in network) echo fsl_edge ;; *) sleep 5 ;; esac\n'
    )

    with pytest.raises(RangeUnavailable, match="did not finish within 1s"):
        substrate.launcher("edge")("fsl-kali", ["sqlmap"], timeout=1)


def test_a_command_that_fails_is_a_command_that_ran(docker_that):
    ran = docker_that(RUNS_WHAT_IT_IS_GIVEN).runner("wiki")(
        ["sh", "-c", "echo no such file >&2; exit 1"]
    )

    assert (ran.exit_code, ran.output) == (1, "no such file\n"), ran


def test_input_reaches_the_command(docker_that):
    ran = docker_that(RUNS_WHAT_IT_IS_GIVEN).runner("sensor")(
        ["cat"], stdin="alert http any\n"
    )

    assert ran.output == "alert http any\n", ran


def test_a_container_that_is_stopped_is_unavailable_not_a_failed_command(docker_that):
    substrate = docker_that(
        "echo 'Error response from daemon: container 92e9bf6c is not running' >&2\n"
        "exit 1\n"
    )

    with pytest.raises(RangeUnavailable, match="is not running"):
        substrate.runner("wiki")(["cat", "/var/log/wiki-reads.log"])


def test_a_daemon_that_is_not_there_is_unavailable_not_a_failed_command(docker_that):
    substrate = docker_that(
        "echo 'Cannot connect to the Docker daemon at unix:///x/docker.sock. "
        "Is the docker daemon running?' >&2\nexit 1\n"
    )

    with pytest.raises(RangeUnavailable, match="Cannot connect"):
        substrate.runner("sensor")(["cat", "/etc/suricata/rules/local.rules"])
