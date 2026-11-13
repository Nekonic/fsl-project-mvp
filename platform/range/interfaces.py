from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

LISTED = "ip -o -4 addr show 2>/dev/null || ifconfig -a inet"
BUSYBOX = "busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"
IP_LINE = re.compile(r"^\d+:\s+(?P<name>[^\s@]+)(?:@\S+)?\s+inet\s+(?P<address>\d+\.\d+\.\d+\.\d+/\d+)")
IFCONFIG_NAME = re.compile(r"^(?P<name>[A-Za-z0-9_.]+):\s+flags=")
IFCONFIG_INET = re.compile(r"^\s+inet\s+(?P<address>\d+\.\d+\.\d+\.\d+)\s+netmask\s+0x(?P<mask>[0-9a-fA-F]{8})")
LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
BRIDGE_PREFIX = "br-"


@dataclass(frozen=True)
class Interface:
    host: str
    name: str
    address: str
    segment: str = ""


def on_this_host(command: str) -> list[str]:
    return ["docker", "run", "--rm", "--network", "host", BUSYBOX, "sh", "-c", command]


def listed(output: str) -> list[tuple[str, str]]:
    found, current = [], ""
    for line in output.splitlines():
        line = line.replace("\\", " ")
        matched = IP_LINE.match(line)
        if matched:
            found.append((matched["name"], matched["address"]))
            continue
        named = IFCONFIG_NAME.match(line)
        if named:
            current = named["name"]
            continue
        inet = IFCONFIG_INET.match(line)
        if inet and current:
            found.append((current, f"{inet['address']}/{bin(int(inet['mask'], 16)).count('1')}"))
    return [(name, address) for name, address in found
            if ipaddress.ip_interface(address).ip not in LOOPBACK]


def on_segment(address: str, subnets: list[tuple[str, str]]) -> str:
    ip = ipaddress.ip_interface(address).ip
    return next((segment for subnet, segment in subnets
                 if subnet and ip in ipaddress.ip_network(subnet, strict=False)), "")


def placed(host: str, output: str, subnets: list[tuple[str, str]]) -> list[Interface]:
    return [Interface(host, name, address, on_segment(address, subnets)) for name, address in listed(output)]


def slot_listed(output: str, project: str) -> tuple[list[tuple[str, str]], dict[str, str]]:
    networks, sections, current = [], {}, ""
    for line in output.splitlines():
        if line.startswith("@network "):
            _, name, *subnets = line.split()
            networks += [(name.removeprefix(f"{project}_"), subnet) for subnet in subnets]
        elif line.startswith("@container "):
            current = line.split(" ", 1)[1].strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return networks, {service: "\n".join(lines) for service, lines in sections.items() if service}
