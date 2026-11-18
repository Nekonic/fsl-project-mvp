from __future__ import annotations

import ipaddress
from dataclasses import dataclass

LAN_TAG = "cr.lan="
DEVICE_TAG = "cr.device="
CONTROL = "control"


@dataclass(frozen=True)
class Interface:
    host: str
    name: str
    address: str
    segment: str = ""
    sensor: bool = False


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
    addresses: tuple[tuple[str, str], ...] = ()
    host: str = ""
    attached: tuple[tuple[str, str], ...] = ()
    links: tuple[tuple[str, str], ...] = ()
    sniffs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Wiring:
    networks: tuple[Network, ...] = ()
    containers: tuple[Container, ...] = ()

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
            found += [Interface(container.host or container.service, name, address, legs.get(name, ""),
                                sensor=bool(container.sniffs))
                      for name, address in container.addresses]
        return found


def _tagged(resource: dict, prefix: str) -> str:
    return next((tag[len(prefix):] for tag in resource.get("tags") or () if tag.startswith(prefix)), "")


def from_docker(networks: list[dict], containers: dict[str, str]) -> tuple:
    found = []
    for network in sorted(networks, key=lambda one: str(one.get("Name") or "")):
        cidrs = tuple(sorted(str(pool["Subnet"]) for pool in (network.get("IPAM") or {}).get("Config") or ()
                             if ":" not in str(pool.get("Subnet") or ":")))
        if not network.get("Internal") or not cidrs:
            continue
        members = tuple(sorted(
            (containers[member["Name"]], member["IPv4Address"], str(member.get("MacAddress") or "").lower())
            for member in (network.get("Containers") or {}).values()
            if member.get("Name") in containers and member.get("IPv4Address")))
        found.append((str(network["Name"]).replace("_", "-"), cidrs, members))
    return tuple(found)


def from_neutron(networks: list[dict], subnets: list[dict], ports: list[dict],
                 extra: dict[str, tuple[str, ...]] | None = None, docker: tuple = ()) -> Wiring:
    lans = {network["id"]: _tagged(network, LAN_TAG) for network in networks if _tagged(network, LAN_TAG)}
    cidrs = {subnet["id"]: subnet["cidr"] for subnet in subnets if subnet.get("network_id") in lans}
    drawn = tuple(sorted((Network(key=lan, bridge=ident, subnets=tuple(sorted(
        subnet["cidr"] for subnet in subnets if subnet.get("network_id") == ident)))
        for ident, lan in lans.items()), key=lambda network: network.key))
    held: dict[str, dict] = {}
    for port in sorted(ports, key=lambda one: (_tagged(one, DEVICE_TAG), _tagged(one, LAN_TAG))):
        device, lan = _tagged(port, DEVICE_TAG), _tagged(port, LAN_TAG)
        if not device or lan == CONTROL or port.get("network_id") not in lans:
            continue
        entry = held.setdefault(device, {"addresses": [], "attached": [], "sniffs": []})
        mac = str(port.get("mac_address") or "").lower()
        entry["attached"].append((lan, mac))
        if port.get("port_security_enabled") is False:
            entry["sniffs"].append(lan)
            continue
        for fixed in port.get("fixed_ips") or ():
            cidr = cidrs.get(fixed.get("subnet_id"))
            if cidr:
                entry["addresses"].append((lan, f"{fixed['ip_address']}/{ipaddress.ip_network(cidr).prefixlen}"))
        entry["addresses"] += [(lan, address) for address in (extra or {}).get(device, ())
                               if (lan, address) not in entry["addresses"]]
    for key, cidrs, members in docker:
        drawn += (Network(key=key, bridge=key, subnets=cidrs),)
        for device, address, mac in members:
            entry = held.setdefault(device, {"addresses": [], "attached": [], "sniffs": []})
            entry["addresses"].append((key, address))
            entry["attached"].append((key, mac))
    return Wiring(networks=drawn, containers=tuple(
        Container(service=device, host=device, addresses=tuple(entry["addresses"]), attached=tuple(entry["attached"]),
                  links=tuple(entry["attached"]), sniffs=tuple(entry["sniffs"]))
        for device, entry in sorted(held.items())))
