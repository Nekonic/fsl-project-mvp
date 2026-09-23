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
TARGET = "target"
SENSOR = "sensor"
WIKI = "wiki"
GATEWAY = "gateway"

ROLES = (ATTACKER, TARGET, SENSOR, WIKI, GATEWAY)

EXIT_MARK = "fsl.exit="
_REPORTED = re.compile(r"(?s)(.*)" + re.escape(EXIT_MARK) + r"(\d+)\n(.*)\Z")

TARGET_NODE = "/nodejs/bin/node"
NODE_REPORT = (
    "const ran = require('child_process').spawnSync("
    "process.argv[1], process.argv.slice(2), {stdio: 'inherit'});"
    "if (ran.error) process.stderr.write(ran.error.message + '\\n');"
    f"process.stderr.write('{EXIT_MARK}' + (ran.error ? 127 : ran.status ?? "
    "128 + require('os').constants.signals[ran.signal]) + '\\n');"
)

class RangeUnavailable(RuntimeError):
    pass

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

def through_node(argv: list[str]) -> list[str]:
    return [TARGET_NODE, "-e", NODE_REPORT, "--", *argv]

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

def declared_roles() -> dict[str, str]:
    document = yaml.safe_load(DECLARATION.read_text()) or {}
    return dict(document.get("roles") or {})

WITHOUT_A_SHELL = {TARGET: through_node}

DOCKER_HOSTS = {
    role: Host(
        node=node, unit=node.removeprefix("fsl-"),
        reporting=WITHOUT_A_SHELL.get(role, through_shell),
    )
    for role, node in declared_roles().items()
}

class Docker:

    def __init__(self, hosts=None, root=REPO_ROOT):
        self.hosts = dict(DOCKER_HOSTS if hosts is None else hosts)
        self.root = Path(root)

    def run(self, role: str, argv, timeout: float = 60.0) -> Ran:
        host = self._host(role)
        done = self._dispatch(
            ["docker", "exec", host.node, *host.reporting(list(argv))], timeout
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

    def segments(self, role: str, timeout: float = 60.0) -> frozenset[str]:
        node = self._host(role).node
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
        unit = self._host(role).unit
        for argv in (["rm", "-sf", unit], ["up", "-d", unit]):
            done = self._dispatch(["docker", "compose", *argv], timeout)
            if done.returncode != 0:
                raise RangeUnavailable(
                    f"could not recreate the host filling {role!r} ({unit}): "
                    f"{(done.stderr or done.stdout).strip()}"
                )

    def start_hint(self, *roles: str, fresh: bool = False) -> str:
        if not roles:
            return "DOCKER_GID=$(bin/docker-gid) docker compose up -d --build"
        units = " ".join(self._host(role).unit for role in roles)
        flag = " --force-recreate" if fresh else ""
        return f"docker compose up -d{flag} {units}"

    def _host(self, role: str) -> Host:
        host = self.hosts.get(role)
        if host is None:
            raise RangeUnavailable(
                f"no host fills the role {role!r}; this range offers "
                f"{sorted(self.hosts)}"
            )
        return host

    def _dispatch(self, command, timeout: float):
        try:
            return subprocess.run(
                command, capture_output=True, text=True,
                timeout=timeout, cwd=self.root,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(
                f"could not reach the range to run {command[0]}: {exc}"
            ) from exc

RANGE = Docker()

def run(role: str, argv, timeout: float = 60.0) -> Ran:
    return RANGE.run(role, argv, timeout=timeout)

def segments(role: str, timeout: float = 60.0) -> frozenset[str]:
    return RANGE.segments(role, timeout=timeout)

def recreate(role: str, timeout: float = 300.0) -> None:
    RANGE.recreate(role, timeout=timeout)

def start_hint(*roles: str, fresh: bool = False) -> str:
    return RANGE.start_hint(*roles, fresh=fresh)
