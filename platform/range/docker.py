from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from dataclasses import replace

from range.declared import Declaration
from range.ports import (
    Node, Ran, RangeUnavailable, Segment, Sensor, Shape, execute, reported,
    reporting,
)

def _one_subnet(network_name: str, config: list) -> str:
    allocated = [entry.get("Subnet", "") for entry in config if entry.get("Subnet")]
    if len(allocated) > 1:
        raise RangeUnavailable(
            f"network {network_name!r} has {len(allocated)} subnets {allocated}; "
            f"alerts are binned by one subnet per segment, so give it exactly one"
        )
    return allocated[0] if allocated else ""

PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
SEGMENT_LABEL = "fsl.segment.id"
ESTATE = "estate"

_TIMEOUT = 30
SESSION_DEADLINE = 540
SESSION_PREFIX = "fsl-"
SESSION_PROJECT = re.compile(r"fsl-(\d+)")

class Docker:
    concurrent_sessions = True

    def __init__(self, declared: Declaration, project: str = "fsl",
                 session_file: str = "session.yaml", session: int | None = None):
        self.declared = declared
        self.project = project
        self.session_file = session_file
        self.session = session

    def for_session(self, session: int | None) -> "Docker":
        return Docker(self.declared, self.project, self.session_file, session)

    def describe(self) -> Shape:
        networks, session = self._networks()
        return Shape(
            segments=tuple(self._placed(networks, session)),
            sensors=self._sensors(networks, session),
        )

    def segments(self) -> tuple[Segment, ...]:
        return tuple(self._placed(*self._networks()))

    def address(self, role: str) -> str:
        return self._address_on(self._container(role), self._network_of(ESTATE))

    def _networks(self) -> tuple[list[dict], str]:
        names, session = self._named(SEGMENT_LABEL)
        if not names:
            raise RangeUnavailable(
                f"no network of project {self.project!r} carries {SEGMENT_LABEL}"
            )

        return [
            json.loads(line)
            for line in self._read(
                ["network", "inspect", "--format", "{{json .}}", *names]
            ).splitlines()
        ], session

    def _session_of(self, projects) -> str:
        if self.session is not None:
            return f"{SESSION_PREFIX}{self.session}"
        numbered = [int(found[1]) for found in map(SESSION_PROJECT.fullmatch, projects) if found]
        return f"{SESSION_PREFIX}{max(numbered)}" if numbered else ""

    def _container(self, role: str) -> str:
        host = self.declared.host(role)
        service = self.declared.compose.get(role)
        if not service:
            return host
        running = [
            line.partition(" ")[::2]
            for line in self._lines([
                "ps", "--filter", f"label={SERVICE_LABEL}={service}",
                "--format", f'{{{{.Names}}}} {{{{.Label "{PROJECT_LABEL}"}}}}',
            ])
        ]
        session = self._session_of(project for _, project in running)
        found = [name for name, project in running if project == session]
        if len(found) != 1:
            raise RangeUnavailable(
                f"{len(found)} containers run the {service!r} service of "
                f"{session or 'no session'}, and {host} has to be exactly one"
            )
        return found[0]

    def _address_on(self, container: str, network: str) -> str:
        attached = json.loads(self._read([
            "inspect", container, "--format", "{{json .NetworkSettings.Networks}}",
        ]) or "{}")
        address = (attached.get(network) or {}).get("IPAddress", "")
        if not address:
            raise RangeUnavailable(f"{container} has no address on {network}")
        return address

    def _node_name(self, name: str, session: str) -> str:
        found = re.fullmatch(rf"{re.escape(session)}-(.+)-\d+", name) if session else None
        if found is None:
            return name
        role = next((r for r, s in self.declared.compose.items() if s == found[1]), "")
        return self.declared.roles.get(role, name)

    def runner(self, role: str, segment_id: str = ""):
        host = self.declared.host(role)

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            command = ["docker", "exec"]
            if stdin is not None:
                command.append("-i")
            command += [self._container(role), *reporting(argv)]
            done = execute(host, command, stdin, timeout)
            ran = reported(done)
            if ran is None:
                said = (done.stderr or done.stdout or "").strip()[:300]
                raise RangeUnavailable(
                    f"{host} never reported the command finishing: "
                    + (said or f"docker exited {done.returncode}")
                )
            return ran

        return run

    def launcher(self, segment_id: str):
        def launch(image: str, argv: list[str], timeout: float = 600.0) -> Ran:
            network = self._network_of(segment_id)
            command = [
                "docker", "run", "--rm", "--network", network,
                *self._served_names(network), image, *argv,
            ]
            try:
                done = subprocess.run(
                    command, capture_output=True, text=True, errors="replace",
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RangeUnavailable(
                    f"{image} did not finish within {timeout:.0f}s and may "
                    f"still be running"
                ) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise RangeUnavailable(f"could not start {image}: {exc}") from exc
            return Ran(
                exit_code=done.returncode,
                output=(done.stdout or "") + (done.stderr or ""),
            )

        return launch

    def _served_names(self, network: str) -> list[str]:
        gateway = self.declared.hosts.get(self.declared.roles.get("gateway", ""))
        if gateway is None or not gateway.names:
            return []
        address = self._address_on(self._container("gateway"), network)
        return [f"--add-host={name}:{address}" for name in gateway.names]

    def _network_of(self, segment_id: str) -> str:
        found, _ = self._named(f"{SEGMENT_LABEL}={segment_id}")
        if len(found) != 1:
            raise RangeUnavailable(
                f"{len(found)} networks of project {self.project!r} carry "
                f"{SEGMENT_LABEL}={segment_id!r}, and a host has to start on "
                f"exactly one"
            )
        return found[0]

    def _placed(self, networks: list[dict], session: str):
        taken: dict[str, str] = {}
        for network in networks:
            segment_id = (network.get("Labels") or {}).get(SEGMENT_LABEL, "")
            if not segment_id:
                continue
            if segment_id in taken:
                raise RangeUnavailable(
                    f"{taken[segment_id]} and {network['Name']} both carry "
                    f"{SEGMENT_LABEL}={segment_id!r}, so nothing says which of "
                    f"them the segment is"
                )
            taken[segment_id] = network["Name"]
            yield self._segment(segment_id, network, session)

    def _segment(self, segment_id: str, network: dict, session: str) -> Segment:
        config = (network.get("IPAM") or {}).get("Config") or [{}]
        nodes = sorted(
            (
                Node(
                    name=self._node_name(attached["Name"], session),
                    address=attached.get("IPv4Address", "").split("/")[0],
                )
                for attached in (network.get("Containers") or {}).values()
            ),
            key=lambda node: node.name,
        )
        return replace(
            self.declared.segment(segment_id),
            subnet=_one_subnet(network["Name"], config),
            network=network["Name"],
            gateway=config[0].get("Gateway", ""),
            nodes=tuple(nodes),
        )

    def _sensors(self, networks: list[dict], session: str) -> tuple[Sensor, ...]:
        if not self.declared.watches:
            return ()

        named = {
            container_id: self._node_name(attached["Name"], session)
            for network in networks
            for container_id, attached in (network.get("Containers") or {}).items()
        }
        watching = sorted(self.declared.watches)
        containers = [self._container(role) for role in watching]
        modes = self._modes(containers)
        found = []
        for (name, host), container in zip(self.declared.watching(), containers):
            sharing = named.get(modes.get(container, "").partition(":")[2], "")
            if sharing != host:
                raise RangeUnavailable(
                    f"{name} is declared to watch {host} and stands in "
                    f"{sharing or modes.get(container, 'nothing')!r} instead, so "
                    f"the console would draw a sensor on traffic it cannot see"
                )
            found.append(Sensor(name=name, watches=host))
        return tuple(found)

    def _modes(self, names: list[str]) -> dict[str, str]:
        modes = {}
        for line in self._read([
            "container", "inspect",
            "--format", "{{.Name}} {{.HostConfig.NetworkMode}}", *names,
        ]).splitlines():
            name, _, mode = line.strip().partition(" ")
            if name:
                modes[name.lstrip("/")] = mode
        return modes

    def open_session(self, session_id: int, live=()) -> None:
        deadline = time.monotonic() + SESSION_DEADLINE
        host_dir = self._host_dir()
        project = f"{SESSION_PREFIX}{session_id}"
        kept = {project, *(f"{SESSION_PREFIX}{n}" for n in live)}
        for ended in self._session_projects():
            if ended not in kept:
                self._detach(ended)
                self._compose(["-p", ended, "down", "-v"], deadline)
        self._compose(
            ["-p", project, "-f", self.session_file,
             "up", "-d", "--wait", "--no-build"],
            deadline, {"FSL_HOST_DIR": host_dir, "FSL_SESSION": str(session_id)},
        )
        for network in self._project_networks(project):
            self._read(["network", "connect", "--alias", "platform", network,
                        socket.gethostname()])

    def _project_networks(self, project: str) -> list[str]:
        return self._lines([
            "network", "ls", "--filter", f"label={PROJECT_LABEL}={project}",
            "--format", "{{.Name}}",
        ])

    def _detach(self, project: str) -> None:
        for network in self._project_networks(project):
            try:
                self._read(["network", "disconnect", "-f", network, socket.gethostname()])
            except RangeUnavailable:
                pass

    def _session_projects(self) -> list[str]:
        listed = json.loads(self._read(["compose", "ls", "--all", "--format", "json"]) or "[]")
        return [
            entry["Name"] for entry in listed
            if SESSION_PROJECT.fullmatch(entry.get("Name", ""))
        ]

    def _host_dir(self) -> str:
        found = self._read([
            "inspect", socket.gethostname(), "--format",
            '{{index .Config.Labels "com.docker.compose.project.working_dir"}}',
        ]).strip()
        if not found:
            raise RangeUnavailable(
                "the platform container carries no compose working_dir label, "
                "so the session stack's bind mounts have no host directory"
            )
        return found

    def _compose(self, argv: list[str], deadline: float,
                 env: dict[str, str] | None = None) -> None:
        left = deadline - time.monotonic()
        if left <= 0:
            raise RangeUnavailable(
                f"docker compose {' '.join(argv[:3])}: the session open spent its "
                f"{SESSION_DEADLINE} s before this step"
            )
        try:
            done = subprocess.run(
                ["docker", "compose", *argv], capture_output=True, text=True,
                timeout=left, env={**os.environ, **(env or {})},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(f"docker compose {' '.join(argv[:3])}: {exc}") from exc
        if done.returncode != 0:
            raise RangeUnavailable(
                f"docker compose {' '.join(argv[:3])}: "
                f"{(done.stderr or done.stdout).strip()[-400:]}"
            )

    def _named(self, label: str) -> tuple[list[str], str]:
        listed = [
            (line.split(" ") + ["", ""])[:3]
            for line in self._lines([
                "network", "ls", "--filter", f"label={label}",
                "--format", f'{{{{.Name}}}} {{{{.Label "{PROJECT_LABEL}"}}}} '
                            f'{{{{.Label "{SEGMENT_LABEL}"}}}}',
            ])
        ]
        session = self._session_of(project for _, project, _ in listed)
        owned = {segment for _, project, segment in listed if session and project == session}
        return [
            name for name, project, segment in listed
            if (project == session and session)
            or (project == self.project and segment not in owned)
        ], session

    def _lines(self, argv: list[str]) -> list[str]:
        return [line.strip() for line in self._read(argv).splitlines() if line.strip()]

    def _read(self, argv: list[str]) -> str:
        try:
            done = subprocess.run(
                ["docker", *argv], capture_output=True, text=True, timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(f"docker {' '.join(argv[:2])}: {exc}") from exc
        if done.returncode != 0:
            raise RangeUnavailable(
                f"docker {' '.join(argv[:2])}: {done.stderr.strip()[:200]}"
            )
        return done.stdout
