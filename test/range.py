from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = REPO_ROOT / "platform" / "range" / "declaration.yaml"
SESSION_STACK = "session.yaml"
SESSION_PROJECT = re.compile(r"fsl-(\d+)")

ATTACKER = "attacker"
BOARD = "board"
BOARD_DB = "board-db"
SENSOR = "sensor"
GATEWAY = "gateway"
SCORER = "scorer"

ROLES = (ATTACKER, BOARD, BOARD_DB, SENSOR, GATEWAY)

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

@dataclass(frozen=True)
class Host:
    node: str
    unit: str
    reporting: Callable[[list[str]], list[str]] = through_shell

def declared(key: str) -> dict[str, str]:
    document = yaml.safe_load(DECLARATION.read_text()) or {}
    return dict(document.get(key) or {})

def declared_roles() -> dict[str, str]:
    return declared("roles")

def declared_on_openstack() -> tuple[dict[str, str], set[str]]:
    document = yaml.safe_load(DECLARATION.read_text()) or {}
    overlay = document.get("openstack") or {}
    roles = {**(document.get("roles") or {}), **(overlay.get("roles") or {})}
    hosts = set(document.get("hosts") or {}) | set(overlay.get("hosts") or {})
    return roles, hosts

DOCKER_HOSTS = {
    role: Host(node=node, unit=declared("compose").get(role, ""))
    for role, node in declared_roles().items()
}

class Docker:
    substrate = "compose"

    def __init__(self, hosts=None, root=REPO_ROOT):
        self.hosts = dict(DOCKER_HOSTS if hosts is None else hosts)
        self.root = Path(root)

    def run(self, role: str, argv, timeout: float = 60.0, session: int | None = None) -> Ran:
        host = self._host(role)
        done = self._dispatch(
            ["docker", "exec", self._node(role, session, timeout),
             *host.reporting(list(argv))],
            timeout,
        )
        finished = reported(done.stderr or "")
        if finished is None:
            said = (done.stderr or done.stdout or "").strip()[:300]
            raise RangeUnavailable(
                f"the host filling {role!r} ({host.node}) never reported the "
                f"command finishing, so it may never have run: "
                + (said or f"docker exited {done.returncode}")
            )
        code, stderr = finished
        return Ran(exit_code=code, stdout=done.stdout, stderr=stderr)

    def segments(self, role: str, timeout: float = 60.0, session: int | None = None) -> frozenset[str]:
        node = self._node(role, session, timeout)
        done = self._dispatch(
            ["docker", "inspect", node, "--format",
             "{{json .NetworkSettings.Networks}}"],
            timeout,
        )
        if done.returncode != 0:
            raise RangeUnavailable(
                f"could not read the segments of the host filling {role!r} "
                f"({node}): {(done.stderr or done.stdout).strip()}"
            )
        try:
            attached = json.loads(done.stdout)
        except ValueError as exc:
            raise RangeUnavailable(
                f"the substrate listed no segments for {role!r}: "
                f"{done.stdout.strip()[:200]}"
            ) from exc
        return frozenset(attached)

    def recreate(self, role: str, timeout: float = 300.0) -> None:
        host = self._host(role)
        project = self._project_of(role, self._node(role, None, timeout), timeout)
        session = project.removeprefix("fsl-")
        for argv in (["rm", "-sf", host.unit], ["up", "-d", host.unit]):
            done = self._dispatch(
                ["docker", "compose", "-p", project, "-f", SESSION_STACK, *argv],
                timeout, {"FSL_SESSION": session},
            )
            if done.returncode != 0:
                raise RangeUnavailable(
                    f"could not recreate the host filling {role!r} ({host.unit}): "
                    f"{(done.stderr or done.stdout).strip()}"
                )

    def _project_of(self, role: str, node: str, timeout: float) -> str:
        done = self._dispatch(
            ["docker", "inspect", node, "--format",
             '{{index .Config.Labels "com.docker.compose.project"}}'],
            timeout,
        )
        project = done.stdout.strip()
        if done.returncode != 0 or not project:
            raise RangeUnavailable(
                f"no session stack holds the host filling {role!r} ({node}): "
                f"{(done.stderr or done.stdout).strip()}"
            )
        return project

    def start_hint(self, *roles: str, fresh: bool = False) -> str:
        if not roles:
            return "docker compose up -d --build, then POST /api/sessions/"
        units = " ".join(self._host(role).unit for role in roles)
        flag = " --force-recreate" if fresh else ""
        return f"docker compose -p fsl-<session> -f {SESSION_STACK} up -d{flag} {units}"

    def _node(self, role: str, session: int | None, timeout: float) -> str:
        host = self._host(role)
        if not host.unit:
            return host.node
        if session is None:
            session = _default_session()
        done = self._dispatch(
            ["docker", "ps", "--filter", f"label=com.docker.compose.service={host.unit}",
             "--format", '{{.Names}} {{.Label "com.docker.compose.project"}}'],
            timeout,
        )
        running = [line.split() for line in done.stdout.splitlines() if len(line.split()) == 2]
        numbered = [int(found[1]) for _, project in running
                    if (found := SESSION_PROJECT.fullmatch(project))]
        wanted = f"fsl-{session if session is not None else max(numbered, default='')}"
        found = [name for name, project in running if project == wanted]
        if done.returncode != 0 or len(found) != 1:
            raise RangeUnavailable(
                f"{len(found)} containers fill the role {role!r} ({host.unit}) "
                f"in {wanted}: {(done.stderr or '').strip()[:200]}"
            )
        return found[0]

    def missing(self, *roles: str) -> list[str]:
        return [role for role in roles if role not in self.hosts]

    def _host(self, role: str) -> Host:
        host = self.hosts.get(role)
        if host is None:
            raise RangeUnavailable(
                f"no host fills the role {role!r}; this range offers "
                f"{sorted(self.hosts)}"
            )
        return host

    def _dispatch(self, command, timeout: float, env: dict[str, str] | None = None):
        try:
            return subprocess.run(
                command, capture_output=True, text=True,
                timeout=timeout, cwd=self.root, env={**os.environ, **(env or {})},
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

class ThroughPlatform:
    substrate = "openstack"

    def __init__(self, scorer=None):
        self.scorer = scorer or Docker()
        self.roles, self.hosts = declared_on_openstack()

    def run(self, role: str, argv, timeout: float = 60.0, session: int | None = None) -> Ran:
        if role == SCORER:
            return self.scorer.run(role, argv, timeout=timeout)
        done = self.scorer._dispatch(
            ["docker", "exec", self.scorer._host(SCORER).node,
             "python", "manage.py", "run_on_role", role,
             json.dumps(stdout_apart(list(argv))), "--timeout", str(timeout)],
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

    def segments(self, role: str, timeout: float = 60.0, session: int | None = None) -> frozenset[str]:
        raise RangeUnavailable(
            f"the harness reads segments from compose containers; on the "
            f"OpenStack range {role!r} is a Nova server"
        )

    def recreate(self, role: str, timeout: float = 300.0) -> None:
        raise RangeUnavailable(
            f"the harness recreates compose containers; on the OpenStack range "
            f"{role!r} is a Nova server the platform rebuilds after a close"
        )

    def start_hint(self, *roles: str, fresh: bool = False) -> str:
        return "bin/cloud up, then wait for GET /api/range/ready/ to say ready"

RANGE: Docker | ThroughPlatform = Docker()
_default_session: Callable[[], int | None] = lambda: None

def default_to(session: Callable[[], int | None]) -> None:
    global _default_session
    _default_session = session

def use(substrate: str) -> None:
    global RANGE
    RANGE = ThroughPlatform() if substrate == ThroughPlatform.substrate else Docker()

def substrate() -> str:
    return RANGE.substrate

def missing(*roles: str) -> list[str]:
    return RANGE.missing(*roles)

def run(role: str, argv, timeout: float = 60.0, session: int | None = None) -> Ran:
    return RANGE.run(role, argv, timeout=timeout, session=session)

def segments(role: str, timeout: float = 60.0, session: int | None = None) -> frozenset[str]:
    return RANGE.segments(role, timeout=timeout, session=session)

def recreate(role: str, timeout: float = 300.0) -> None:
    RANGE.recreate(role, timeout=timeout)

def start_hint(*roles: str, fresh: bool = False) -> str:
    return RANGE.start_hint(*roles, fresh=fresh)
