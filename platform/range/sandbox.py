from __future__ import annotations

import base64
import ipaddress
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from range import clock
from range.ports import RangeUnavailable

DEFINITION = "wargames/{wargame}/topology.yaml"
COMPOSE = "wargames/{wargame}/compose.yaml"
SENSOR_CONFIG = "deploy/suricata/suricata.yaml"
BASELINE_RULES = "deploy/suricata/rules/local.rules"
YAML_HEADER = "%YAML 1.1\n---\n"
ROLES = ("kali", "infra", "waf", "target")
EVERYWHERE = "0.0.0.0/0"
SKIPPED_HOSTS = 9
STATE = "/var/lib/cr"
READY = f"{STATE}/ready"
FAILED = f"{STATE}/failed"
BOOT = f"{STATE}/boot.sh"
BOOT_LOG = "/var/log/cr-boot.log"
KALI_ADDRESSES = f"{STATE}/kali.ip"
EDGE_RULES = f"{STATE}/edge.nft"
SENSOR_TEMPLATE = f"{STATE}/suricata.yaml"
SENSOR_FILE = "/etc/suricata/suricata.yaml"
SHIPPING = "/etc/rsyslog.d/60-cr.conf"
TARGET_COMPOSE = "/opt/cr/compose.yaml"
TARGET_PROJECT = "cr"
TARGET_WAIT = 600
SHIPPED_PORT = 514
BRIDGE = "br-ids"
LEG_UNMANAGED = "/run/systemd/network/10-cr-{leg}.network"
WEB_USER = "www-data:adm"
USER_DATA_LIMIT = 65535
TAG = re.compile(r"\$\{CR_IMAGE_TAG(?::-[^}]*)?\}")
DROPPED = ("build", "networks", "platform")
WAN = "@wan@"
SNIFFED = "@ids@"
DEV = "@dev@"
FINDS_DEVICE = ("dev() { found=$(ip -o -4 addr show | awk -v a=\"$1\" "
                "'{ split($4, p, \"/\"); if (p[1] == a) { print $2; exit } }'); "
                "[ -n \"$found\" ] || { echo \"no interface holds $1\" >&2; return 1; }; echo \"$found\"; }")


@dataclass(frozen=True)
class Port:
    node: str
    device: str
    lan: str
    address: str = ""
    name: str = ""
    ids: bool = False
    sniffed: bool = False
    origins: bool = False
    forwards: bool = False
    pairs: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()

    @property
    def secured(self) -> bool:
        return not self.ids


@dataclass(frozen=True)
class Device:
    name: str
    node: str
    roles: tuple[str, ...] = ()
    container: str = ""
    rules: str = ""
    reload: str = ""
    pid: str = ""
    names: tuple[str, ...] = ()
    logs: dict[str, str] = field(default_factory=dict)
    upstreams: dict[str, str] = field(default_factory=dict)
    publish: tuple[int, ...] = ()
    extra_hosts: tuple[str, ...] = ()
    forwards: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Definition:
    wargame: str
    lans: dict[str, tuple[str, ...]]
    nodes: dict[str, str]
    ports: tuple[Port, ...]
    devices: dict[str, Device]
    watches: dict[str, str] = field(default_factory=dict)
    compose: dict = field(default_factory=dict)
    sensor_config: str = ""
    baseline_rules: str = ""

    def filling(self, role: str) -> Device:
        found = [device for device in self.devices.values() if role in device.roles]
        if len(found) != 1:
            raise RangeUnavailable(f"{self.wargame}'s topology has {len(found)} devices in the role {role!r}")
        return found[0]

    def on(self, device: str) -> list[Port]:
        return [port for port in self.ports if port.device == device]

    def check(self) -> None:
        unknown = sorted({role for role in self.nodes.values()} - set(ROLES))
        if unknown:
            raise ValueError(f"{self.wargame}: node roles {unknown} are none of {list(ROLES)}")
        for port in self.ports:
            if port.lan not in self.lans:
                raise ValueError(f"{self.wargame}: {port.node} has a port on {port.lan!r}, which no LAN names")
            if port.device not in self.devices or self.devices[port.device].node != port.node:
                raise ValueError(f"{self.wargame}: {port.node}'s port on {port.lan} is for {port.device!r}, "
                                 f"which is no device of {port.node}")
            inside = [ipaddress.ip_network(cidr) for cidr in self.lans[port.lan]]
            if port.address and not any(ipaddress.ip_address(port.address) in net for net in inside):
                raise ValueError(f"{self.wargame}: {port.node}'s {port.address} is outside {port.lan} "
                                 f"{list(self.lans[port.lan])}")
            if not port.address and not port.origins:
                raise ValueError(f"{self.wargame}: {port.node}'s port on {port.lan} has no fixed IP, and Nova "
                                 f"boots no port without one")
        for device in self.devices.values():
            if device.node not in self.nodes:
                raise ValueError(f"{self.wargame}: {device.name} runs on {device.node!r}, which is no node")
        legs = [port for port in self.ports if port.ids]
        if legs and (len(legs) != 2 or len({port.node for port in legs}) != 1
                     or sum(port.sniffed for port in legs) != 1):
            raise ValueError(f"{self.wargame}: an inline IDS is two legs on one node, one of them sniffed")
        roles = [role for device in self.devices.values() for role in device.roles]
        twice = sorted({role for role in roles if roles.count(role) > 1})
        if twice:
            raise ValueError(f"{self.wargame}: roles {twice} are filled by more than one device")


@dataclass(frozen=True)
class Lan:
    name: str
    cidrs: tuple[str, ...]


@dataclass(frozen=True)
class Node:
    name: str
    role: str
    ports: tuple[Port, ...]
    user_data: str


@dataclass(frozen=True)
class Sandbox:
    slot: int
    wargame: str
    lans: tuple[Lan, ...]
    nodes: tuple[Node, ...]
    logged: str = ""

    @property
    def ports(self) -> list[Port]:
        return [port for node in self.nodes for port in node.ports]

    def node(self, name: str) -> Node:
        return next(node for node in self.nodes if node.name == name)


def _port(node: str, entry: dict) -> Port:
    return Port(node=node, device=entry["device"], lan=entry["lan"], address=str(entry.get("address") or ""),
                name=str(entry.get("as") or ""), ids=bool(entry.get("ids")), sniffed=bool(entry.get("sniffed")),
                origins=bool(entry.get("origins")), forwards=bool(entry.get("forwards")))


def _device(name: str, entry: dict) -> Device:
    return Device(
        name=name, node=entry["node"], roles=tuple(entry.get("roles") or ()),
        container=str(entry.get("container") or ""), rules=str(entry.get("rules") or ""),
        reload=str(entry.get("reload") or ""), pid=str(entry.get("pid") or ""),
        names=tuple(entry.get("names") or ()), logs=dict(entry.get("logs") or {}),
        upstreams={str(key): str(value) for key, value in (entry.get("upstreams") or {}).items()},
        publish=tuple(int(port) for port in entry.get("publish") or ()),
        extra_hosts=tuple(entry.get("extra_hosts") or ()),
        forwards={int(port): str(device) for port, device in (entry.get("forwards") or {}).items()},
    )


def wargames(source: Path) -> tuple[str, ...]:
    return tuple(sorted(path.parent.name for path in Path(source).glob(DEFINITION.format(wargame="*"))))


def read(source: Path, wargame: str) -> Definition:
    source = Path(source)
    path = source / DEFINITION.format(wargame=wargame)
    if not path.is_file():
        raise RangeUnavailable(f"the wargame {wargame!r} has no topology at {path}")
    document = yaml.safe_load(path.read_text()) or {}
    compose = source / COMPOSE.format(wargame=wargame)
    found = Definition(
        wargame=wargame,
        lans={name: tuple(cidrs) for name, cidrs in (document.get("lans") or {}).items()},
        nodes={name: entry["role"] for name, entry in (document.get("nodes") or {}).items()},
        ports=tuple(_port(name, port) for name, entry in (document.get("nodes") or {}).items()
                    for port in entry.get("ports") or ()),
        devices={name: _device(name, entry) for name, entry in (document.get("devices") or {}).items()},
        watches=dict(document.get("watches") or {}),
        compose=yaml.safe_load(compose.read_text()) if compose.is_file() else {},
        sensor_config=(source / SENSOR_CONFIG).read_text(),
        baseline_rules=(source / BASELINE_RULES).read_text(),
    )
    found.check()
    return found


def origin_addresses(cidr: str, count: int) -> list[str]:
    hosts = ipaddress.ip_network(cidr).hosts()
    return [str(address) for _, address in zip(range(SKIPPED_HOSTS + count), hosts)][SKIPPED_HOSTS:]


def default_origin(origins, chosen: str):
    by_id = {origin.id: origin for origin in origins}
    return by_id.get(chosen) or (origins[0] if origins else None)


def internet_side(origins, chosen: str) -> str:
    origin = default_origin(origins, chosen)
    return origin_addresses(origin.subnet, 1)[0] if origin is not None else ""


def sender(device: str, slot: int) -> str:
    return device if slot == 1 else f"{device}-{slot}"


def _addressed(ports, origins, chosen: str) -> tuple[Port, ...]:
    placed = []
    source = internet_side(origins, chosen)
    ordered = sorted(origins, key=lambda origin: origin.id != chosen)
    for port in ports:
        if port.origins:
            extra = tuple(f"{address}/{ipaddress.ip_network(origin.subnet).prefixlen}"
                          for origin in ordered for address in origin_addresses(origin.subnet, origin.addresses)
                          if address != source)
            port = Port(**{**vars(port), "address": source, "extra": extra})
        if port.origins or port.forwards:
            port = Port(**{**vars(port), "pairs": (EVERYWHERE,)})
        placed.append(port)
    return tuple(placed)


def plan(definition: Definition, slot: int, origins, chosen_origin: str, collector: str,
         collector_port: int, image_tag: str) -> Sandbox:
    if not origins:
        raise RangeUnavailable("the declaration names no origin, so Kali would stand on no Internet address")
    first = default_origin(origins, chosen_origin)
    lans = []
    for name, cidrs in definition.lans.items():
        held = tuple(cidrs) + ((first.subnet,) if any(p.origins and p.lan == name for p in definition.ports) else ())
        lans.append(Lan(name=name, cidrs=held))
    ports = _addressed(definition.ports, origins, chosen_origin)
    upstream = internet_side(origins, chosen_origin)
    context = _Context(definition, slot, ports, upstream, collector, collector_port, image_tag)
    nodes = tuple(Node(name=name, role=role, ports=tuple(port for port in ports if port.node == name),
                       user_data=context.user_data(name, role))
                  for name, role in definition.nodes.items())
    logged = next(port.lan for port in ports if port.device == definition.filling("log-server").name)
    return Sandbox(slot=slot, wargame=definition.wargame, lans=tuple(lans), nodes=nodes, logged=logged)


class _Literal(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _text(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


_Literal.add_representer(str, _text)


def edge_rules(wan_address: str, forwarded: dict[int, str]) -> str:
    dnat = "".join(f'    iifname "{WAN}" ip daddr {wan_address} tcp dport {port} dnat to {address}\n'
                   for port, address in sorted(forwarded.items()))
    return (
        "table ip nat\ndelete table ip nat\ntable ip nat {\n"
        "  chain prerouting {\n    type nat hook prerouting priority dstnat; policy accept;\n" + dnat + "  }\n}\n"
        "table ip inbound\ndelete table ip inbound\ntable ip inbound {\n"
        "  chain forward {\n    type filter hook forward priority filter; policy accept;\n"
        f'    iifname "{WAN}" ct state established,related accept\n'
        f'    iifname "{WAN}" ct status dnat accept\n'
        f'    iifname "{WAN}" drop\n'
        "  }\n"
        "  chain input {\n    type filter hook input priority filter; policy accept;\n"
        f'    iifname "{WAN}" ct state established,related accept\n'
        f'    iifname "{WAN}" icmp type echo-request accept\n'
        f'    iifname "{WAN}" drop\n'
        "  }\n}\n"
    )


def sensor_config(text: str) -> str:
    config = yaml.safe_load(text.removeprefix(YAML_HEADER))
    config["af-packet"] = [{"interface": SNIFFED, "cluster-id": 99, "cluster-type": "cluster_flow",
                            "defrag": True, "threads": 1}]
    return YAML_HEADER + yaml.dump(config, Dumper=_Literal, sort_keys=False)


def kali_addresses(port: Port, router: str) -> str:
    lines = [f"addr add {address} dev {DEV}" for address in port.extra]
    lines.append(f"route replace default via {router} dev {DEV} onlink src {port.address}")
    return "".join(f"{line}\n" for line in lines)


def _template(name: str, host: str, tag: str) -> str:
    return (f'template(name="{name}" type="string" string="<%PRI%>1 %TIMESTAMP:::date-rfc3339% {host} {tag} '
            f'%PROCID% %MSGID% %STRUCTURED-DATA% %msg%\\n")\n')


def _read_file(path: str, tag: str, ruleset: str) -> str:
    return (f'input(type="imfile" File="{path}" Tag="{tag}" Facility="local2" Severity="info" '
            f'reopenOnTruncate="on" freshStartTail="on" ruleset="{ruleset}")\n')


def _forward(target: str, port: int, protocol: str, template: str = "") -> str:
    shaped = f' Template="{template}"' if template else ' Template="RSYSLOG_SyslogProtocol23Format"'
    return (f'action(type="omfwd" Target="{target}" Port="{port}" Protocol="{protocol}"{shaped} '
            f'action.resumeRetryCount="-1")')


class _Context:
    def __init__(self, definition, slot, ports, upstream, collector, collector_port, image_tag):
        self.definition, self.slot, self.ports = definition, slot, ports
        self.upstream, self.collector, self.collector_port, self.image_tag = (
            upstream, collector, collector_port, image_tag)

    def _of(self, device: str) -> list[Port]:
        return [port for port in self.ports if port.device == device]

    def _role(self, role: str) -> Device:
        return self.definition.filling(role)

    def _shared(self, device: str, peer: str) -> tuple[Port, Port]:
        for port in self._of(device):
            for other in self._of(peer):
                if other.lan == port.lan:
                    return port, other
        raise RangeUnavailable(f"{device} and {peer} share no LAN in {self.definition.wargame}'s topology")

    def user_data(self, node: str, role: str) -> str:
        files, steps = getattr(self, f"_{role}")(node)
        files = {clock.TIMESYNCD: clock.timesyncd(self.collector), **files}
        script = "\n".join(["#!/bin/sh", "set -eu", FINDS_DEVICE, *steps,
                            "systemctl restart systemd-timesyncd", ""])
        files[BOOT] = script
        document = {
            "write_files": [{"path": path, "permissions": "0755" if path == BOOT else "0644", "content": content}
                            for path, content in files.items()],
            "runcmd": [["sh", "-c", f"mkdir -p {STATE} && sh {BOOT} >{BOOT_LOG} 2>&1 && touch {READY} "
                                    f"|| {{ touch {FAILED}; tail -n 20 {BOOT_LOG} > /dev/console; }}"]],
        }
        text = "#cloud-config\n" + yaml.dump(document, Dumper=_Literal, sort_keys=False, width=1 << 16)
        encoded = len(base64.b64encode(text.encode()))
        if encoded > USER_DATA_LIMIT:
            raise RangeUnavailable(f"{node} needs {encoded} bytes of user data and Nova takes at most "
                                   f"{USER_DATA_LIMIT}")
        return text

    def _kali(self, node: str):
        kali = self._role("attacker")
        port = next(port for port in self._of(kali.name) if port.origins)
        edge = self._role("edge")
        wan = next(other for other in self._of(edge.name) if other.lan == port.lan)
        names = self._role("gateway").names
        steps = [f"internet=$(dev {port.address})",
                 f'sed "s/{DEV}/$internet/g" {KALI_ADDRESSES} | ip -batch -',
                 "printf '%s\\n' " + " ".join(shlex.quote(f"{wan.address} {name}") for name in names)
                 + " >> /etc/hosts"]
        return {KALI_ADDRESSES: kali_addresses(port, wan.address)}, steps

    def _infra(self, node: str):
        files, steps = {}, []
        devices = {device.name for device in self.definition.devices.values() if device.node == node}
        edge = self._role("edge") if self._role("edge").name in devices else None
        sensor = self._role("sensor") if self._role("sensor").name in devices else None
        if edge is not None:
            wan = next(port for port in self._of(edge.name) if port.name == "wan")
            forwarded = {number: self._shared(edge.name, device)[1].address for number, device in edge.forwards.items()}
            files[EDGE_RULES] = edge_rules(wan.address, forwarded)
            steps += [f"wan=$(dev {wan.address})",
                      "sysctl -qw net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.default.rp_filter=0",
                      f'ip route replace default via {self.upstream} dev "$wan" onlink',
                      f'sed "s/{WAN}/$wan/g" {EDGE_RULES} | nft -f -']
        if sensor is not None:
            legs = [port for port in self._of(sensor.name) if port.ids]
            steps += [f"leg{at}=$(dev {port.address})" for at, port in enumerate(legs)]
            sniffed = next(at for at, port in enumerate(legs) if port.sniffed)
            for at in range(len(legs)):
                steps += [f'printf "[Match]\\nName=%s\\n[Link]\\nUnmanaged=yes\\n" "$leg{at}" '
                          f'> {LEG_UNMANAGED.format(leg=f"$leg{at}")}']
            steps += ["networkctl reload",
                      f"ip link show {BRIDGE} >/dev/null 2>&1 || "
                      f"ip link add {BRIDGE} type bridge stp_state 0 forward_delay 0"]
            for at in range(len(legs)):
                steps += [f'ip addr flush dev "$leg{at}"', f'ip link set "$leg{at}" master {BRIDGE} up',
                          f'ethtool -K "$leg{at}" tso off gso off gro off >/dev/null 2>&1 || true']
            steps += [f"ip link set {BRIDGE} up",
                      f'sed "s/{SNIFFED}/$leg{sniffed}/g" {SENSOR_TEMPLATE} > {SENSOR_FILE}']
            files[SENSOR_TEMPLATE] = sensor_config(self.definition.sensor_config)
            files[sensor.rules] = self.definition.baseline_rules
            steps += ["systemctl restart suricata"]
        shipped = self._relay(node, devices)
        if shipped:
            files[SHIPPING] = shipped
            steps += self._rsyslog_restart()
        return files, steps

    def _rsyslog_restart(self) -> list[str]:
        return ["grep -q maxMessageSize /etc/rsyslog.conf || "
                "sed -i '1i global(maxMessageSize=\"64k\")' /etc/rsyslog.conf",
                "systemctl restart rsyslog"]

    def _relay(self, node: str, devices: set[str]) -> str:
        server = self._role("log-server")
        if server.name not in devices:
            return ""
        listening = self._of(server.name)[0]
        parts = ['module(load="imtcp")\n', 'module(load="imfile")\n',
                 f'input(type="imtcp" port="{SHIPPED_PORT}" address="{listening.address}" ruleset="cr-relayed")\n']
        relays, local = [], []
        for device in sorted(self.definition.devices.values(), key=lambda one: one.name):
            for tag, path in sorted(device.logs.items()):
                template = f"{device.name}-{tag}"
                parts.append(_template(template, sender(device.name, self.slot), tag))
                send = _forward(self.collector, self.collector_port, "udp", template)
                if device.node == node:
                    parts.append(_read_file(path, tag, f"{template}-local"))
                    local.append(f'ruleset(name="{template}-local") {{\n    {send}\n}}\n')
                else:
                    shipping = next(port for port in self._of(device.name) if port.lan == listening.lan)
                    relays.append(f'    if $fromhost-ip == "{shipping.address}" and $programname == "{tag}" then {{\n'
                                  f'        {send}\n        stop\n    }}\n')
        return "".join(parts + local) + 'ruleset(name="cr-relayed") {\n' + "".join(relays) + "    stop\n}\n"

    def _waf(self, node: str):
        waf = self._role("gateway")
        edge = self._role("edge")
        own, router = self._shared(waf.name, edge.name)
        server = self._of(self._role("log-server").name)[0]
        steps = [f"dmz=$(dev {own.address})",
                 f'ip route replace default via {router.address} dev "$dmz"',
                 "printf '%s\\n' " + " ".join(shlex.quote(f"{address} {name}")
                                              for name, address in sorted(waf.upstreams.items())) + " >> /etc/hosts"]
        for path in sorted(waf.logs.values()):
            steps += [f"install -d -m 0755 {shlex.quote(str(Path(path).parent))}",
                      f"[ -f {shlex.quote(path)} ] || install -m 0644 /dev/null {shlex.quote(path)}",
                      f"chown {WEB_USER} {shlex.quote(path)}"]
        shipping = "".join(['module(load="imfile")\n']
                           + [_read_file(path, tag, "cr-shipped") for tag, path in sorted(waf.logs.items())]
                           + ['ruleset(name="cr-shipped") {\n    '
                              + _forward(server.address, SHIPPED_PORT, "tcp") + "\n}\n"])
        steps += ["systemctl restart nginx", *self._rsyslog_restart()]
        return {SHIPPING: shipping}, steps

    def _target(self, node: str):
        document = target_compose(self.definition, self.image_tag)
        steps = [f"docker compose -p {TARGET_PROJECT} -f {TARGET_COMPOSE} up -d --wait "
                 f"--wait-timeout {TARGET_WAIT} --pull never"]
        return {TARGET_COMPOSE: yaml.dump(document, Dumper=_Literal, sort_keys=True)}, steps


def target_compose(definition: Definition, image_tag: str) -> dict:
    if not image_tag:
        raise RangeUnavailable("the target runs the wargame images by the range images' tag; set CR_RANGE_IMAGE_TAG")
    by_container = {device.container: device for device in definition.devices.values() if device.container}
    services = {}
    for name, service in (definition.compose.get("services") or {}).items():
        kept = {key: value for key, value in service.items() if key not in DROPPED}
        kept["image"] = TAG.sub(image_tag, kept["image"])
        kept["container_name"] = name
        kept["hostname"] = name
        kept["restart"] = "unless-stopped"
        device = by_container.get(name)
        if device is not None:
            address = next((port.address for port in definition.on(device.name)), "")
            if device.publish:
                kept["ports"] = [f"{address}:{port}:{port}" for port in device.publish]
            if device.extra_hosts:
                kept["extra_hosts"] = list(device.extra_hosts)
        services[name] = kept
    unplaced = sorted(set(by_container) - set(services))
    if unplaced:
        raise RangeUnavailable(f"{definition.wargame}'s topology runs {unplaced}, which its compose.yaml lacks")
    return {"name": TARGET_PROJECT, "services": services}
