import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

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
        f"compose project cr belongs to whichever checkout last ran up, so "
        f"restarting another tree's stack makes acceptance test that tree's "
        f"code while saying it tested this one. docker was called with:\n{docker}\n{done.stdout}"
    )
    if brought_up == elsewhere:
        assert done.returncode == 1 and str(elsewhere) in done.stdout, done.stdout



FAILING_PLAY = """LISTENERS = []


def play(wargame):
    raise RuntimeError("no slot came free for board")
"""

READY_PLAY = """from types import SimpleNamespace

LISTENERS = []


def play(wargame):
    return SimpleNamespace(allocation=5)


def sensor_runs_the_declared_rules(played):
    return "ok"


def close(played):
    return SimpleNamespace(ok=True, text="")
"""


@pytest.mark.parametrize("plays, accepted", [(FAILING_PLAY, False), (READY_PLAY, True)], ids=["no-slot", "target-up"])
def test_acceptance_starts_only_after_the_warm_up_round_found_the_target_up(tmp_path, checkout, plays, accepted):
    acceptance = tmp_path / "acceptance-ran"
    executable(checkout / ".venv/bin/python",
               f'case "$1" in -) exec "{sys.executable}" "$@" ;; bin/acceptance) touch "{acceptance}" ;; esac\n'
               "exit 0\n")
    (checkout / "test").mkdir()
    (checkout / "test/plays.py").write_text(plays)
    executable(tmp_path / "tools/docker", f'case "$1" in inspect) echo "{checkout}" ;; esac\nexit 0\n')
    executable(tmp_path / "tools/curl", "exit 0\n")

    done = subprocess.run([str(checkout / "bin/verify")], capture_output=True, text=True, timeout=60, cwd=checkout,
                          env={**os.environ, "PATH": f"{tmp_path / 'tools'}:/usr/bin:/bin"})

    assert acceptance.exists() == accepted, done.stdout + done.stderr
    if not accepted:
        assert done.returncode == 1
        assert "no allocation got a slot" in done.stdout and "no slot came free for board" in done.stderr
