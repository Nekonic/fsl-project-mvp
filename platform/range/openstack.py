from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace

from range.declared import Declaration
from range.ports import Node, Ran, RangeUnavailable, Segment, Sensor, Shape

TOKEN = "POST {keystone}/v3/auth/tokens"
NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"

CALLS = (TOKEN, NETWORKS, SUBNETS, SERVERS)

FIXED = "OS-EXT-IPS:type"

WATCHED_ROLE = "gateway"
SENSOR_ROLE = "sensor"


def unimplemented(call: str) -> dict:
    raise NotImplementedError(
        f"the sketch issues no cloud call; a real adapter would send {call}, "
        f"authenticated by the first of {CALLS}"
    )


@dataclass(frozen=True)
class Cloud:
    keystone: str
    neutron: str
    nova: str
    project: str
    ssh_user: str
    ssh_key: str


class OpenStack:
    def __init__(self, declared: Declaration, cloud: Cloud, get=unimplemented):
        self.declared = declared
        self.cloud = cloud
        self.get = get

    def describe(self) -> Shape:
        bound = self._bind(self._ask(NETWORKS)["networks"])
        servers = self._ask(SERVERS)["servers"]

        segments = []
        for declared in self.declared.segments:
            network = bound.get(declared.id)
            if network is None:
                raise RangeUnavailable(
                    f"the declaration names the segment {declared.id!r} and "
                    f"project {self.cloud.project!r} has no network called that"
                )
            allocated = self._ask(SUBNETS, network=network["id"])["subnets"]
            first = allocated[0] if allocated else {}
            segments.append(
                replace(
                    declared,
                    subnet=first.get("cidr", ""),
                    network=network["id"],
                    gateway=first.get("gateway_ip", ""),
                    nodes=self._nodes(declared.id, servers),
                )
            )

        return Shape(segments=tuple(segments), sensors=self._sensors(servers))

    def runner(self, role: str, segment_id: str = ""):
        host = self.declared.roles.get(role)
        if host is None:
            raise RangeUnavailable(f"no host fills the role {role!r}")

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            address = self._address(role, host, segment_id)
            command = [
                "ssh", "-i", self.cloud.ssh_key, "-o", "BatchMode=yes",
                f"{self.cloud.ssh_user}@{address}", *argv,
            ]
            try:
                done = subprocess.run(
                    command, input=stdin, capture_output=True,
                    text=True, timeout=timeout,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RangeUnavailable(f"could not reach {host}: {exc}") from exc
            if done.returncode == 255:
                raise RangeUnavailable(f"no ssh to {host} at {address}")
            return Ran(
                exit_code=done.returncode,
                output=(done.stdout or "") + (done.stderr or ""),
            )

        return run

    def _bind(self, networks: list[dict]) -> dict[str, dict]:
        declared = {segment.id for segment in self.declared.segments}
        found: dict[str, dict] = {}
        for network in networks:
            name = network["name"]
            if name not in declared:
                continue
            if name in found:
                raise RangeUnavailable(
                    f"two Neutron networks are named {name!r}; the declaration "
                    f"binds a segment by name and Neutron does not keep names "
                    f"unique, so nothing says which one the segment is"
                )
            found[name] = network
        return found

    def _nodes(self, segment_id: str, servers: list[dict]) -> tuple[Node, ...]:
        found = [
            Node(name=server["name"], address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(segment_id, [])
            if entry.get(FIXED) == "fixed"
        ]
        return tuple(sorted(found, key=lambda node: node.name))

    def _sensors(self, servers: list[dict]) -> tuple[Sensor, ...]:
        sensor = self.declared.roles.get(SENSOR_ROLE, "")
        watched = self.declared.roles.get(WATCHED_ROLE, "")
        standing = {server["name"] for server in servers}
        if sensor in standing and watched in standing:
            return (Sensor(name=sensor, watches=watched),)
        return ()

    def _address(self, role: str, host: str, segment_id: str) -> str:
        for segment in self.describe().segments:
            if segment_id and segment.id != segment_id:
                continue
            for node in segment.nodes:
                if node.name == host:
                    return node.address
        raise RangeUnavailable(
            f"the host filling {role!r} ({host}) stands on no segment this "
            f"platform can address"
        )

    def _ask(self, call: str, **binding) -> dict:
        return self.get(
            call.format(
                keystone=self.cloud.keystone,
                neutron=self.cloud.neutron,
                nova=self.cloud.nova,
                project=self.cloud.project,
                **binding,
            )
        )
