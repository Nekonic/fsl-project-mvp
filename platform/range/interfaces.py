from __future__ import annotations

import ipaddress
import re
import socket
import struct
from dataclasses import dataclass

ROUTES = "cat /proc/net/route 2>/dev/null || netstat -rn -f inet"
LISTED = f"ip -o -4 addr show 2>/dev/null || ifconfig -a inet; {ROUTES}"
CONTAINERS = (
    "docker network ls --no-trunc --format '@network {{.ID}} {{.Name}}'\n"
    "for c in $(docker ps -q); do\n"
    "  set -- $(docker inspect -f '{{index .Config.Labels \"com.docker.compose.service\"}} "
    "{{.State.Pid}} {{.HostConfig.NetworkMode}}' \"$c\")\n"
    "  [ \"$3\" = host ] && continue\n"
    "  echo \"@container $1\"\n"
    "  nsenter -t \"$2\" -n ip -o -4 addr show\n"
    "  nsenter -t \"$2\" -n cat /proc/net/route\n"
    "done"
)
MACS = f'for i in /sys/class/net/*; do echo "${{i##*/}} $(cat "$i/address")"; done; {ROUTES}'
IP_LINE = re.compile(r"^\d+:\s+(?P<name>[^\s@]+)(?:@\S+)?\s+inet\s+(?P<address>\d+\.\d+\.\d+\.\d+/\d+)")
IFCONFIG_NAME = re.compile(r"^(?P<name>[A-Za-z0-9_.]+):\s+flags=")
IFCONFIG_INET = re.compile(r"^\s+inet\s+(?P<address>\d+\.\d+\.\d+\.\d+)\s+netmask\s+0x(?P<mask>[0-9a-fA-F]{8})")
LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
DEFAULT = "00000000"
NETSTAT_DEFAULT = "default"
BRIDGE_PREFIX = "br-"
BRIDGE_ID = 12

@dataclass(frozen=True)
class Interface:
    host: str
    name: str
    address: str
    segment: str = ""
    gateway: str = ""

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

def routed(output: str) -> dict[str, str]:
    found = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[1] == DEFAULT and fields[7] == DEFAULT and fields[2] != DEFAULT:
            found.setdefault(fields[0], socket.inet_ntoa(struct.pack("<I", int(fields[2], 16))))
        elif len(fields) >= 4 and fields[0] == NETSTAT_DEFAULT and fields[1][:1].isdigit():
            found.setdefault(fields[3], fields[1])
    return found

def on_segment(address: str, subnets: list[tuple[str, str]]) -> str:
    ip = ipaddress.ip_interface(address).ip
    return next((segment for subnet, segment in subnets
                 if subnet and ip in ipaddress.ip_network(subnet, strict=False)), "")

def placed(host: str, output: str, subnets: list[tuple[str, str]]) -> list[Interface]:
    gateways = routed(output)
    return [Interface(host, name, address, on_segment(address, subnets), gateways.get(name, ""))
            for name, address in listed(output)]

def network_switch(network: str) -> str:
    return network.replace("_", "-")

def containers(host_output: str, output: str, named=lambda service: service) -> tuple[list[tuple[str, str]], dict]:
    networks = {}
    sections: dict[str, list[str]] = {}
    current = ""
    for line in output.splitlines():
        if line.startswith("@network "):
            _, ident, name = line.split(" ", 2)
            networks[BRIDGE_PREFIX + ident[:BRIDGE_ID]] = name
        elif line.startswith("@container "):
            current = line.split(" ", 1)[1].strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    bridges = [(str(ipaddress.ip_interface(address).network), network_switch(networks[name]))
               for name, address in listed(host_output) if name in networks]
    return bridges, {named(service): "\n".join(lines) for service, lines in sections.items() if service}

def by_mac(macs_output: str, attached: list[tuple[str, str, str]], host: str) -> list[Interface]:
    names = {}
    for line in macs_output.splitlines():
        name, _, mac = line.strip().partition(" ")
        if mac:
            names[mac.lower()] = name
    gateways = routed(macs_output)
    return [Interface(host, names[mac.lower()], address, segment, gateways.get(names[mac.lower()], ""))
            for mac, address, segment in attached if names.get(mac.lower())]
