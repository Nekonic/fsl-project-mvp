from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace

from range.declared import Declaration
from range.ports import Node, Ran, RangeUnavailable, Segment, Sensor, Shape

TOKEN = "POST {keystone}/v3/auth/tokens"
NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags-any={tags}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"
BOOT = "POST {nova}/servers"

CALLS = (TOKEN, NETWORKS, SUBNETS, SERVERS, BOOT)

FIXED = "OS-EXT-IPS:type"
PAGE_LIMIT = 50
VERSION = "version"

SEGMENT_TAG = "fsl.segment.id"


def _next(links) -> str:
    for link in links or []:
        if link.get("rel") == "next" and link.get("href"):
            return link["href"]
    return ""

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
        wanted = ",".join(
            f"{SEGMENT_TAG}={segment.id}" for segment in self.declared.segments
        )
        bound = self._bind(self._all(NETWORKS, "networks", tags=wanted))
        servers = self._all(SERVERS, "servers")

        segments = []
        for declared in self.declared.segments:
            network = bound.get(declared.id)
            if network is None:
                raise RangeUnavailable(
                    f"the declaration names the segment {declared.id!r} and no "
                    f"network of project {self.cloud.project!r} is tagged "
                    f"{SEGMENT_TAG}={declared.id}"
                )
            allocated = self._all(SUBNETS, "subnets", network=network["id"])
            first = allocated[0] if allocated else {}
            segments.append(
                replace(
                    declared,
                    subnet=first.get("cidr", ""),
                    network=network["id"],
                    gateway=first.get("gateway_ip", ""),
                    nodes=self._nodes(network["name"], servers),
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

    def launcher(self, segment_id: str):
        def launch(image: str, argv: list[str], timeout: float = 600.0) -> Ran:
            return self._ask(BOOT, network=segment_id)

        return launch

    def _bind(self, networks: list[dict]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for network in networks:
            for tag in network.get("tags") or []:
                mark, _, segment_id = tag.partition("=")
                if mark != SEGMENT_TAG or not segment_id:
                    continue
                if segment_id in found:
                    raise RangeUnavailable(
                        f"{found[segment_id]['id']} and {network['id']} both "
                        f"carry {SEGMENT_TAG}={segment_id!r}, so nothing says "
                        f"which of them the segment is"
                    )
                found[segment_id] = network
        return found

    def _nodes(self, network_name: str, servers: list[dict]) -> tuple[Node, ...]:
        found = [
            Node(name=server["name"], address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(network_name, [])
            if entry.get(FIXED) == "fixed" and entry.get(VERSION, 4) == 4
        ]
        return tuple(sorted(found, key=lambda node: node.name))

    def _sensors(self, servers: list[dict]) -> tuple[Sensor, ...]:
        standing = {server["name"] for server in servers}
        found = []
        for sensing, sensed in sorted(self.declared.watches.items()):
            name = self.declared.roles[sensing]
            host = self.declared.roles[sensed]
            if name in standing and host in standing:
                found.append(Sensor(name=name, watches=host))
        return tuple(found)

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

    def _all(self, call: str, key: str, **binding) -> list:
        page = self._ask(call, **binding)
        found = list(page.get(key) or [])

        for _ in range(PAGE_LIMIT):
            href = _next(page.get(f"{key}_links"))
            if not href:
                return found
            page = self.get(f"GET {href}")
            found += list(page.get(key) or [])

        raise RangeUnavailable(
            f"{key} came back in more than {PAGE_LIMIT} pages, each one "
            f"pointing at the next; the cloud is looping or the range is not "
            f"what this platform is for"
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
