from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = REPO_ROOT / "platform" / "range" / "declaration.yaml"

ATTACKER = "attacker"
TARGET = "target"
SENSOR = "sensor"
WIKI = "wiki"
GATEWAY = "gateway"

ROLES = (ATTACKER, TARGET, SENSOR, WIKI, GATEWAY)

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

@dataclass(frozen=True)
class Host:
    node: str
    unit: str

def declared_roles() -> dict[str, str]:
    document = yaml.safe_load(DECLARATION.read_text()) or {}
    return dict(document.get("roles") or {})

DOCKER_HOSTS = {
    role: Host(node=node, unit=node.removeprefix("fsl-"))
    for role, node in declared_roles().items()
}

class Docker:

    def __init__(self, hosts=None, root=REPO_ROOT):
        self.hosts = dict(DOCKER_HOSTS if hosts is None else hosts)
        self.root = Path(root)

    def run(self, role: str, argv, timeout: float = 60.0) -> Ran:
        node = self._host(role).node
        done = self._dispatch(["docker", "exec", node, *argv], timeout)
        merged = done.stdout + done.stderr
        if done.returncode == 126 or "No such container" in merged:
            raise RangeUnavailable(
                f"the host filling {role!r} ({node}) is not running, so the "
                f"command never ran"
            )
        return Ran(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

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
