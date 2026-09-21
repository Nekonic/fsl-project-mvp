from __future__ import annotations

import json
import subprocess
from dataclasses import replace

from range.declared import Declaration
from range.ports import Node, Ran, RangeUnavailable, Segment, Sensor, Shape

PROJECT_LABEL = "com.docker.compose.project"

_TIMEOUT = 30

class Docker:
    def segment_id(self, network_name: str) -> str:
        prefix = self.project + "_"
        if network_name.startswith(prefix):
            return network_name[len(prefix):]
        return network_name

    def __init__(self, declared: Declaration, project: str = "fsl"):
        self.declared = declared
        self.project = project

    def describe(self) -> Shape:
        names = self._lines([
            "network", "ls", "--filter", f"label={PROJECT_LABEL}={self.project}",
            "--format", "{{.Name}}",
        ])
        if not names:
            raise RangeUnavailable(f"project {self.project!r} has no networks")

        networks = [
            json.loads(line)
            for line in self._read(
                ["network", "inspect", "--format", "{{json .}}", *names]
            ).splitlines()
        ]

        return Shape(
            segments=tuple(self._segment(network) for network in networks),
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

    def _segment(self, network: dict) -> Segment:
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
            self.declared.segment(self.segment_id(network["Name"])),
            subnet=config[0].get("Subnet", ""),
            network=network["Name"],
            gateway=config[0].get("Gateway", ""),
            nodes=tuple(nodes),
        )

    def _sensors(self, networks: list[dict]) -> tuple[Sensor, ...]:
        named = {
            container_id: attached["Name"]
            for network in networks
            for container_id, attached in (network.get("Containers") or {}).items()
        }
        found = []
        for name, mode in self._modes().items():
            if not mode.startswith("container:"):
                continue
            host = named.get(mode.split(":", 1)[1])
            if host:
                found.append(Sensor(name=name, watches=host))
        return tuple(sorted(found, key=lambda sensor: sensor.name))

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
