import http.server
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import threading
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


@pytest.fixture
def sensor_refusing():
    refusal = {"ok": False, "output": 'E: detect-parse: no terminating ";" found at line 3'}

    class Refusing(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps(refusal).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], refusal["output"]
    server.shutdown()


def test_a_rule_file_the_sensor_refuses_is_reported_with_the_sensors_reason(
    tmp_path, checkout, sensor_refusing
):
    port, reason = sensor_refusing
    rules = checkout / "deploy/suricata/rules/local.rules"
    rules.parent.mkdir(parents=True)
    rules.write_text('alert http any any -> any any (msg:"x"; sid:1\n')
    executable(
        checkout / ".venv/bin/python",
        '[ "$1" = - ] || exit 0\n'
        'script="$(cat)"\n'
        'case "$script" in *api/rules/validate*) ;; *) exit 0 ;; esac\n'
        f'printf "%s\\n" "$script" | sed "s#localhost:8000#127.0.0.1:{port}#" '
        f'| exec {shlex.quote(sys.executable)} -\n',
    )
    executable(tmp_path / "tools/curl", "exit 0\n")
    executable(
        tmp_path / "tools/docker",
        f'case "$1" in inspect) echo "{checkout}" ;; *) exit 0 ;; esac\n',
    )
    unproxied = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}

    done = subprocess.run(
        [str(checkout / "bin/verify")],
        capture_output=True, text=True, timeout=60,
        env={
            **unproxied,
            "PATH": f"{tmp_path / 'tools'}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
        },
    )

    said = done.stdout + done.stderr
    assert reason in said, (
        f"the sensor said why it refused the rule file and verify threw that "
        f"away:\n{said}"
    )
    assert "bind-mounted files were replaced" not in said, (
        f"a rule the sensor cannot parse was blamed on the bind mounts, and "
        f"the fix offered was a recreate that leaves the rule broken:\n{said}"
    )


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
