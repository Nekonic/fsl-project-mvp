import os
import shutil
import stat
import subprocess
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


@pytest.mark.parametrize("owner", ["elsewhere", "this checkout"])
def test_only_a_stack_brought_up_from_this_checkout_is_restarted(tmp_path, checkout, verify_against, owner):
    elsewhere = tmp_path / "someone-elses-worktree"
    elsewhere.mkdir()
    brought_up = checkout if owner == "this checkout" else elsewhere

    done, docker = verify_against(f'echo "{brought_up}"')

    assert (RESTART in docker) == (brought_up == checkout), (
        f"compose project fsl belongs to whichever checkout last ran up, so "
        f"restarting another tree's stack makes acceptance test that tree's "
        f"code while saying it tested this one. docker was called with:\n{docker}\n{done.stdout}"
    )
    if brought_up == elsewhere:
        assert done.returncode == 1 and str(elsewhere) in done.stdout, done.stdout


def test_a_fast_check_whose_measure_refuses_does_not_pass(checkout):
    executable(
        checkout / "bin/measure",
        "echo 'measure: compose.override.yml exists, and Compose merges it "
        "into the stack' >&2\n"
        "exit 1\n",
    )

    done = subprocess.run(
        [str(checkout / "bin/verify"), "--fast"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
    )

    assert done.returncode != 0 and "fast check passed" not in done.stdout, (
        f"measure could not read this tree and --fast called the baseline "
        f"green anyway. The full run at the end fails on the same refusal, "
        f"and the session protocol answers that with git reset --hard, so the "
        f"session's work is thrown away every time:\n{done.stdout}"
    )
    assert "measure" in done.stdout, done.stdout
