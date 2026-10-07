from __future__ import annotations

import base64
import ipaddress
import itertools
import shlex
from dataclasses import dataclass

import yaml

from range import fabric
from range.declared import Declaration

HOST = "fsl_host"
GATEWAY_ROLE = "gateway"
EDGE_ROLE = "edge"
ATTACKER_ROLE = "attacker"
NAMED_ON = "estate"

@dataclass(frozen=True)
class Port:
    host: str
    segment: str
    name: str
    fixed_ips: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True)
class Plan:
    boot: tuple[str, ...] = ()
    ports: tuple[Port, ...] = ()
    standing: tuple[tuple[str, str, str], ...] = ()
    blocked: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.boot or self.ports or self.blocked)

    @property
    def active(self) -> bool:
        return (
            self.clean
            and bool(self.standing)
            and all(status == "ACTIVE" for _, _, status in self.standing)
        )

def port_name(host: str, segment: str) -> str:
    return f"{host}.{segment}"

def _gateways(network: dict, subnets: list) -> tuple[tuple[str, str], ...]:
    return tuple(
        (subnet["id"], subnet["gateway_ip"])
        for subnet in subnets
        if subnet["network_id"] == network["id"] and subnet.get("gateway_ip")
    )

def origin_addresses(cidr: str, count: int) -> list[str]:
    hosts = ipaddress.ip_network(cidr).hosts()
    return [str(address) for address in itertools.islice(hosts, 9, 9 + count)]

def _attacker_addresses(network: dict, subnets: list, origins) -> tuple[tuple[str, str], ...]:
    by_cidr = {origin.subnet: origin for origin in origins}
    return tuple(
        (subnet["id"], address)
        for subnet in subnets
        if subnet["network_id"] == network["id"] and subnet["cidr"] in by_cidr
        for address in origin_addresses(subnet["cidr"], by_cidr[subnet["cidr"]].addresses)
    )

def edge_of(declaration: Declaration) -> str:
    return declaration.roles.get(EDGE_ROLE) or declaration.roles.get(GATEWAY_ROLE, "")

def plan(declaration: Declaration, networks: list, subnets: list, ports: list,
         servers: list, ready: dict) -> Plan:
    bound = fabric.bound(declaration, networks)
    outside = {origin.segment for origin in declaration.origins}
    edge = edge_of(declaration)
    attacker = declaration.roles.get(ATTACKER_ROLE, "")
    may_stand_outside = {host for host in (edge, attacker) if host}
    named = {(port.get("network_id"), port.get("name")) for port in ports}
    boot, create, standing, blocked = [], [], [], []
    for host, entry in declaration.hosts.items():
        server = next(
            (s for s in servers if (s.get("metadata") or {}).get(HOST) == host), None
        )
        if server is not None:
            standing.append((host, server["id"], server.get("status", "")))
            continue
        reasons = [
            f"the fabric has no network for {segment}, which {host} stands on"
            for segment in entry.segments if segment not in bound
        ]
        if host not in ready:
            reasons.append(f"image {host} is not ready")
        if fabric.MANAGEMENT not in entry.segments:
            reasons.append(f"{host} is not on {fabric.MANAGEMENT}, where the platform reaches it")
        reasons += [
            f"{host} is declared on {segment}, where only the edge and the "
            f"attacker stand"
            for segment in entry.segments if segment in outside and host not in may_stand_outside
        ]
        if reasons:
            blocked += reasons
            continue
        boot.append(host)
        for segment in entry.segments:
            name = port_name(host, segment)
            if (bound[segment]["id"], name) in named:
                continue
            if host == edge:
                fixed = _gateways(bound[segment], subnets)
            elif host == attacker and segment in outside:
                fixed = _attacker_addresses(bound[segment], subnets, declaration.origins)
            else:
                fixed = ()
            create.append(Port(host=host, segment=segment, name=name, fixed_ips=fixed))
    return Plan(boot=tuple(boot), ports=tuple(create), standing=tuple(standing),
                blocked=tuple(blocked))

def user_data(names: dict, mac: str = "", addresses: tuple[str, ...] = ()) -> str:
    document = {
        "manage_etc_hosts": False,
        "write_files": [{
            "path": "/etc/hosts",
            "append": True,
            "content": "".join(
                f"{address} {' '.join(known)}\n" for address, known in names.items()
            ),
        }],
    }
    if addresses:
        script = (
            f"for nic in /sys/class/net/*; do "
            f"if [ \"$(cat $nic/address)\" = {shlex.quote(mac)} ]; then "
            f"for address in {' '.join(map(shlex.quote, addresses))}; do "
            f"ip addr replace \"$address\" dev \"${{nic##*/}}\"; done; fi; done"
        )
        document["bootcmd"] = [["sh", "-c", script]]
    return base64.b64encode(("#cloud-config\n" + yaml.safe_dump(document)).encode()).decode()
