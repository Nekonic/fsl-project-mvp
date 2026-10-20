from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = REPO_ROOT / "platform" / "range" / "declaration.yaml"

ATTACKER = "attacker"
BOARD = "board"
SENSOR = "sensor"
SCORER = "scorer"

EXIT_MARK = "fsl.exit="
_REPORTED = re.compile(r"(?s)(.*)" + re.escape(EXIT_MARK) + r"(\d+)\n(.*)\Z")

class RangeUnavailable(RuntimeError):
    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output

def _said(stream) -> str:
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream or ""

@dataclass(frozen=True)
class Ran:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

def through_shell(argv: list[str]) -> list[str]:
    return [
        "sh", "-c", "--",
        f'{shlex.join(argv)}; printf "{EXIT_MARK}%d\\n" "$?" >&2',
    ]

def reported(stderr: str) -> tuple[int, str] | None:
    found = _REPORTED.match(stderr)
    if found is None:
        return None
    return int(found[2]), found[1] + found[3]

def declared(key: str) -> dict[str, str]:
    document = yaml.safe_load(DECLARATION.read_text()) or {}
    return dict(document.get(key) or {})

def declared_roles() -> dict[str, str]:
    return declared("roles")

def declared_hosts() -> set[str]:
    return set(declared("hosts"))

class Platform:
    def __init__(self, node=None, root=REPO_ROOT):
        self.node = node or declared_roles()[SCORER]
        self.root = Path(root)

    def run(self, argv, timeout: float = 60.0) -> Ran:
        done = self.dispatch(["docker", "exec", self.node, *through_shell(list(argv))], timeout)
        finished = reported(done.stderr or "")
        if finished is None:
            said = (done.stderr or done.stdout or "").strip()[:300]
            raise RangeUnavailable(
                f"the platform ({self.node}) never reported the command "
                f"finishing, so it may never have run: "
                + (said or f"docker exited {done.returncode}")
            )
        code, stderr = finished
        return Ran(exit_code=code, stdout=done.stdout, stderr=stderr)

    def dispatch(self, command, timeout: float):
        try:
            return subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, cwd=self.root,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(
                f"could not reach the range to run {command[0]}: {exc}",
                _said(getattr(exc, "stdout", None)),
            ) from exc

STDOUT_END = "fsl.stdout.end"
PLATFORM_ANSWER = "fsl.platform.answer="

def stdout_apart(argv: list[str]) -> list[str]:
    return ["sh", "-c", f'"$@"; code=$?; printf "\\n%s\\n" {STDOUT_END}; exit $code',
            "sh", *argv]

def split_output(output: str) -> tuple[str, str]:
    stdout, found, stderr = output.partition(f"\n{STDOUT_END}\n")
    return (stdout, stderr) if found else (output, "")

def as_the_terminal(argv: list[str]) -> list[str]:
    return ["bash", "-lc", shlex.join(argv)]

class ThroughPlatform:
    in_the_terminal = {ATTACKER}

    def __init__(self, platform=None):
        self.platform = platform or Platform()
        self.roles, self.hosts = declared_roles(), declared_hosts()

    def run(self, role: str, argv, timeout: float = 60.0, session: int | None = None) -> Ran:
        if role == SCORER:
            return self.platform.run(argv, timeout=timeout)
        if session is None:
            session = _default_session()
        argv = as_the_terminal(list(argv)) if role in self.in_the_terminal else list(argv)
        done = self.platform.dispatch(
            ["docker", "exec", self.platform.node,
             "python", "manage.py", "run_on_role", role,
             json.dumps(stdout_apart(argv)), "--timeout", str(timeout),
             *(["--session", str(session)] if session is not None else [])],
            timeout + 60,
        )
        answer = next((line[len(PLATFORM_ANSWER):] for line in done.stdout.splitlines()
                       if line.startswith(PLATFORM_ANSWER)), None)
        if done.returncode != 0 or answer is None:
            said = (done.stderr or done.stdout or "").strip()[-500:]
            raise RangeUnavailable(
                f"the platform could not run the command on the host filling "
                f"{role!r} ({self.roles.get(role, 'no host')}): "
                + (said or f"docker exited {done.returncode}")
            )
        ran = json.loads(answer)
        stdout, stderr = split_output(ran["output"])
        return Ran(exit_code=ran["exit_code"], stdout=stdout, stderr=stderr)

    def missing(self, *roles: str) -> list[str]:
        return [f"{role} ({self.roles.get(role, 'no host')})" for role in roles
                if self.roles.get(role) not in self.hosts]

RANGE = ThroughPlatform()
_default_session: Callable[[], int | None] = lambda: None

def default_to(session: Callable[[], int | None]) -> None:
    global _default_session
    _default_session = session

def missing(*roles: str) -> list[str]:
    return RANGE.missing(*roles)

def run(role: str, argv, timeout: float = 60.0, session: int | None = None) -> Ran:
    return RANGE.run(role, argv, timeout=timeout, session=session)

def start_hint() -> str:
    return "bin/cloud up, then wait for GET /api/range/ready/ to say ready"
