from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from range import rangehost

IP_LINE = re.compile(r"^\d+:\s+(?P<name>[^\s@]+)(?:@\S+)?\s+inet\s+(?P<address>\d+\.\d+\.\d+\.\d+/\d+)")
LINK_LINE = re.compile(r"^\d+:\s+(?P<name>[^\s@:]+)(?:@[^\s:]+)?:\s.*\slink/ether\s+(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})")
LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
DEFAULT_BRIDGE = "br-{id}"
BRIDGE_ID = 12


@dataclass(frozen=True)
class Interface:
    host: str
    name: str
    address: str
    segment: str = ""


@dataclass(frozen=True)
class Network:
    key: str
    bridge: str
    subnets: tuple[str, ...]

    def holds(self, address: str) -> bool:
        ip = ipaddress.ip_interface(address).ip
        return any(ip in ipaddress.ip_network(subnet, strict=False) for subnet in self.subnets)


@dataclass(frozen=True)
class Container:
    service: str
    mode: str
    args: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()
    addresses: tuple[tuple[str, str], ...] = ()
    host: str = ""
    attached: tuple[tuple[str, str], ...] = ()
    links: tuple[tuple[str, str], ...] = ()

    @property
    def sniffs(self) -> str:
        return next((found["bridge"] for found in map(rangehost.SNIFFS.match, self.args) if found), "")

    def keeps(self, path: str) -> bool:
        return any(path == mount or path.startswith(mount.rstrip("/") + "/") for mount in self.mounts)


@dataclass(frozen=True)
class Wiring:
    networks: tuple[Network, ...] = ()
    containers: tuple[Container, ...] = ()
    forwarded: tuple[str, ...] = ()
    port: str = ""

    def network(self, key: str) -> Network | None:
        return next((network for network in self.networks if network.key == key), None)

    def bridged(self, bridge: str) -> Network | None:
        return next((network for network in self.networks if network.bridge == bridge), None)

    def legs(self, container: Container) -> dict[str, str]:
        by_mac = {mac: network for network, mac in container.attached if mac}
        found = {name: by_mac[mac] for name, mac in container.links if mac in by_mac and self.network(by_mac[mac])}
        for name, address in container.addresses:
            network = next((network for network in self.networks if network.holds(address)), None)
            if network is not None:
                found.setdefault(name, network.key)
        return found

    def interfaces(self) -> list[Interface]:
        found = []
        for container in self.containers:
            legs = self.legs(container)
            found += [Interface(container.host or container.service, name, address, legs.get(name, ""))
                      for name, address in container.addresses]
        return found

    def logging(self) -> list[Container]:
        return [container for container in self.containers
                if any(container.keeps(path) for path in self.forwarded)]


def addressed(output: str) -> list[tuple[str, str]]:
    found = []
    for line in output.splitlines():
        matched = IP_LINE.match(line.replace("\\", " "))
        if matched and ipaddress.ip_interface(matched["address"]).ip not in LOOPBACK:
            found.append((matched["name"], matched["address"]))
    return found


def linked(output: str) -> list[tuple[str, str]]:
    return [(found["name"], found["mac"]) for found in map(LINK_LINE.match, output.splitlines()) if found]


def _network(project: str, fields: list[str]) -> Network:
    name, identity, bridge, *subnets = fields + ["-"] * max(0, 3 - len(fields))
    return Network(key=name.removeprefix(f"{project}_"),
                   bridge=bridge if bridge != "-" else DEFAULT_BRIDGE.format(id=identity[:BRIDGE_ID]),
                   subnets=tuple(subnets))


def wiring(output: str, project: str) -> Wiring:
    networks, containers, forwarded, port = [], [], [], ""
    current: dict | None = None

    def close():
        if current and current["service"]:
            containers.append(Container(service=current["service"], mode=current["mode"],
                                        args=tuple(current["args"]), mounts=tuple(current["mounts"]),
                                        addresses=tuple(addressed("\n".join(current["lines"]))),
                                        attached=tuple(current["attached"]),
                                        links=tuple(linked("\n".join(current["lines"])))))

    for line in output.splitlines():
        if line.startswith("@network "):
            networks.append(_network(project, line.split()[1:]))
        elif line.startswith("@container "):
            close()
            service, _, mode = line.removeprefix("@container ").strip().partition(" ")
            current = {"service": service, "mode": mode.strip(), "args": [], "mounts": [], "attached": [],
                       "lines": []}
        elif line.startswith("@args") and current is not None:
            current["args"] = line.removeprefix("@args").split()
        elif line.startswith("@leg ") and current is not None:
            network, _, mac = line.removeprefix("@leg ").strip().partition(" ")
            current["attached"].append((network.removeprefix(f"{project}_"), mac.strip().lower()))
        elif line.startswith("@mount ") and current is not None:
            current["mounts"].append(line.removeprefix("@mount ").strip())
        elif line.startswith("@forward "):
            forwarded.append(line.removeprefix("@forward ").strip())
        elif line.startswith("@port "):
            port = line.removeprefix("@port ").strip()
        elif current is not None:
            current["lines"].append(line)
    close()
    return Wiring(networks=tuple(networks), containers=tuple(containers), forwarded=tuple(forwarded), port=port)
