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


def test_output_that_is_not_utf8_does_not_crash_the_runner(docker_that):
    substrate = docker_that("printf 'a\\377b'\n")

    ran = substrate.runner("wiki")(["cat", "/var/log/wiki-reads.log"])

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
