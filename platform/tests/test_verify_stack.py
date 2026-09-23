import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.stands_in_for_docker

ROOT = Path(__file__).resolve().parents[2]
RESTART = "compose restart platform"


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "platform").mkdir(parents=True)
    (root / "bin").mkdir()
    shutil.copy(ROOT / "bin/verify", root / "bin/verify")
    executable(root / ".venv/bin/python", "exit 0\n")
    return root.resolve()


@pytest.fixture
def verify_against(tmp_path, checkout):
    calls = tmp_path / "docker-calls"

    def run(inspect):
        executable(
            tmp_path / "tools/docker",
            f'echo "$*" >> "{calls}"\n'
            f'case "$1" in inspect) {inspect} ;; *) exit 1 ;; esac\n',
        )
        done = subprocess.run(
            [str(checkout / "bin/verify")],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": f"{tmp_path / 'tools'}:/usr/bin:/bin"},
        )
        return done, calls.read_text() if calls.exists() else ""

    return run


def test_a_stack_brought_up_from_another_checkout_is_not_restarted(
    tmp_path, verify_against
):
    elsewhere = tmp_path / "someone-elses-worktree"
    elsewhere.mkdir()

    done, docker = verify_against(f'echo "{elsewhere}"')

    assert RESTART not in docker, (
        f"compose project fsl belongs to whichever checkout last ran up, so "
        f"this restarted {elsewhere} and acceptance would test that tree's "
        f"code while saying it tested this one. docker was called with:\n{docker}"
    )
    assert done.returncode == 1 and str(elsewhere) in done.stdout, done.stdout


def test_a_platform_that_is_not_there_is_named_not_restarted(verify_against):
    done, docker = verify_against(
        "echo 'Error: No such object: fsl-platform' >&2; exit 1"
    )

    assert RESTART not in docker, docker
    assert done.returncode == 1 and "fsl-platform" in done.stdout, done.stdout


def test_a_stack_brought_up_from_this_checkout_is_restarted(
    checkout, verify_against
):
    done, docker = verify_against(f'echo "{checkout}"')

    assert RESTART in docker, (
        f"the guard refused the checkout that owns the stack:\n{done.stdout}"
    )


def test_a_measure_that_crashes_is_reported_as_a_crash_not_a_regression(
    tmp_path, checkout
):
    executable(
        checkout / ".venv/bin/python",
        '[ "$1" = - ] || exit 0\n'
        'script="$(cat)"\n'
        'case "$script" in *bin/measure*) ;; *) exit 0 ;; esac\n'
        f'printf "%s\\n" "$script" | exec {shlex.quote(sys.executable)} -\n',
    )
    executable(
        checkout / "bin/measure",
        "echo 'Traceback (most recent call last):' >&2\n"
        "echo \"FileNotFoundError: No such file: 'platform/gone.py'\" >&2\n"
        "exit 1\n",
    )
    (checkout / "metrics.json").write_text(
        '{"core_loc": 1, "dependencies": 1, "services": 1, "tests": 1}\n'
    )
    executable(tmp_path / "tools/curl", "exit 0\n")
    executable(
        tmp_path / "tools/docker",
        f'case "$1" in inspect) echo "{checkout}" ;; *) exit 0 ;; esac\n',
    )

    done = subprocess.run(
        [str(checkout / "bin/verify")],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": f"{tmp_path / 'tools'}:/usr/bin:/bin"},
    )

    assert "measure crashed" in done.stdout, done.stdout
    assert "platform/gone.py" in done.stdout, done.stdout
    assert "metrics regressed" not in done.stdout, (
        f"measure itself failed, so nothing was compared; calling that a "
        f"regression sends the reader looking for a number that grew:\n"
        f"{done.stdout}"
    )
