from __future__ import annotations

import json
import subprocess
from dataclasses import replace

from range.declared import Declaration
from range.ports import Node, Ran, RangeUnavailable, Segment, Sensor, Shape

def _one_subnet(network_name: str, config: list) -> str:
    allocated = [entry.get("Subnet", "") for entry in config if entry.get("Subnet")]
    if len(allocated) > 1:
        raise RangeUnavailable(
            f"the segment {network_name!r} carries {len(allocated)} subnets "
            f"{allocated} and alerts are binned by exactly one. Which one is a "
            f"decision nobody has taken."
        )
    return allocated[0] if allocated else ""

PROJECT_LABEL = "com.docker.compose.project"
SEGMENT_LABEL = "fsl.segment.id"

_TIMEOUT = 30

class Docker:
    def __init__(self, declared: Declaration, project: str = "fsl"):
        self.declared = declared
        self.project = project

    def describe(self) -> Shape:
        names = self._lines([
            "network", "ls",
            "--filter", f"label={PROJECT_LABEL}={self.project}",
            "--filter", f"label={SEGMENT_LABEL}",
            "--format", "{{.Name}}",
        ])
        if not names:
            raise RangeUnavailable(
                f"no network of project {self.project!r} carries {SEGMENT_LABEL}"
            )

        networks = [
            json.loads(line)
            for line in self._read(
                ["network", "inspect", "--format", "{{json .}}", *names]
            ).splitlines()
        ]

        return Shape(
            segments=tuple(self._placed(networks)),
            sensors=self._sensors(networks),
        )

    def runner(self, role: str, segment_id: str = ""):
        host = self.declared.roles.get(role)
        if host is None:
            raise RangeUnavailable(f"no host fills the role {role!r}")

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            command = ["docker", "exec"]
            if stdin is not None:
                command.append("-i")
            command += [host, *argv]
            try:
                done = subprocess.run(
                    command, input=stdin, capture_output=True,
                    text=True, timeout=timeout,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RangeUnavailable(f"could not reach {host}: {exc}") from exc
            output = (done.stdout or "") + (done.stderr or "")
            if done.returncode == 126 or "No such container" in output:
                raise RangeUnavailable(f"{host} is not running")
            return Ran(exit_code=done.returncode, output=output)

        return run

    def launcher(self, segment_id: str):
        def launch(image: str, argv: list[str], timeout: float = 600.0) -> Ran:
            command = [
                "docker", "run", "--rm",
                "--network", self._network_of(segment_id),
                image, *argv,
            ]
            try:
                done = subprocess.run(
                    command, capture_output=True, text=True, timeout=timeout,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RangeUnavailable(f"could not start {image}: {exc}") from exc
            return Ran(
                exit_code=done.returncode,
                output=(done.stdout or "") + (done.stderr or ""),
            )

        return launch

    def _network_of(self, segment_id: str) -> str:
        found = self._lines([
            "network", "ls",
            "--filter", f"label={PROJECT_LABEL}={self.project}",
            "--filter", f"label={SEGMENT_LABEL}={segment_id}",
            "--format", "{{.Name}}",
        ])
        if len(found) != 1:
            raise RangeUnavailable(
                f"{len(found)} networks of project {self.project!r} carry "
                f"{SEGMENT_LABEL}={segment_id!r}, and a host has to start on "
                f"exactly one"
            )
        return found[0]

    def _placed(self, networks: list[dict]):
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
            yield self._segment(segment_id, network)

    def _segment(self, segment_id: str, network: dict) -> Segment:
        config = (network.get("IPAM") or {}).get("Config") or [{}]
        nodes = sorted(
            (
                Node(
                    name=attached["Name"],
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
            gateway=(config[0].get("Gateway", "") if config else ""),
            nodes=tuple(nodes),
        )

    def _sensors(self, networks: list[dict]) -> tuple[Sensor, ...]:
        if not self.declared.watches:
            return ()

        named = {
            container_id: attached["Name"]
            for network in networks
            for container_id, attached in (network.get("Containers") or {}).items()
        }
        modes = self._modes()
        found = []
        for sensing, sensed in sorted(self.declared.watches.items()):
            name = self.declared.roles[sensing]
            host = self.declared.roles[sensed]
            sharing = named.get(modes.get(name, "").partition(":")[2], "")
            if sharing != host:
                raise RangeUnavailable(
                    f"{name} is declared to watch {host} and stands in "
                    f"{sharing or modes.get(name, 'nothing')!r} instead, so "
                    f"the console would draw a sensor on traffic it cannot see"
                )
            found.append(Sensor(name=name, watches=host))
        return tuple(found)

    def _modes(self) -> dict[str, str]:
        names = self._lines([
            "ps", "--filter", f"label={PROJECT_LABEL}={self.project}",
            "--format", "{{.Names}}",
        ])
        if not names:
            raise RangeUnavailable(f"nothing of project {self.project!r} is running")

        modes = {}
        for line in self._read([
            "container", "inspect",
            "--format", "{{.Name}} {{.HostConfig.NetworkMode}}", *names,
        ]).splitlines():
            name, _, mode = line.strip().partition(" ")
            if name:
                modes[name.lstrip("/")] = mode
        return modes

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
                f"docker {' '.join(argv[:2])}: {done.stderr.strip()[:200]} "
                f"The shape of the range can only be read from the range."
            )
        return done.stdout
