from __future__ import annotations

import base64
import ipaddress
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sandbox.runner import RangeUnavailable

DEFINITION = "wargames/{wargame}/topology.yaml"
ROLES = ("kali", "infra", "waf", "target")
EVERYWHERE = "0.0.0.0/0"
SKIPPED_HOSTS = 9
SLOT_ENV = "/etc/slot.env"
STATE = "/var/lib/cr"
READY = f"{STATE}/ready"
FAILED = f"{STATE}/failed"
SHIPPED_PORT = 514
USER_DATA_LIMIT = 65535
BOOTS = {"kali": ("slot-boot.service",), "waf": ("slot-boot.service", "nginx.service"),
         "infra": ("slot-boot.service", "sensor.service"), "target": ("wargames.service",)}
ANSWER_WAIT = 300
WARGAME_COMPOSE = "/opt/wargames/*/compose.yaml"
SUDO = "ALL=(ALL) NOPASSWD:ALL"
TIMESYNCD = "/etc/systemd/timesyncd.conf.d/60-cr.conf"


def timesyncd(server: str) -> str:
    return f"[Time]\nNTP={server}\n"


@dataclass(frozen=True)
class Port:
    node: str
    device: str
    lan: str
    address: str = ""
    ids: bool = False
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
    baseline: str = ""
    files: tuple[str, ...] = ()
    reload: str = ""
    pid: str = ""
    names: tuple[str, ...] = ()
    upstreams: dict[str, str] = field(default_factory=dict)
    forwards: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Definition:
    wargame: str
    lans: dict[str, tuple[str, ...]]
    nodes: dict[str, str]
    ports: tuple[Port, ...]
    devices: dict[str, Device]
    watches: dict[str, str] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)

    def filling(self, role: str) -> Device:
        found = [device for device in self.devices.values() if role in device.roles]
        if len(found) != 1:
            raise RangeUnavailable(f"{self.wargame}'s topology has {len(found)} devices in the role {role!r}")
        return found[0]

    def check(self) -> None:
        unknown = sorted(set(self.nodes.values()) - set(ROLES))
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
        if legs and (len(legs) != 2 or len({port.node for port in legs}) != 1):
            raise ValueError(f"{self.wargame}: an inline IDS is two legs on one node")
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
    env: dict[str, str] = field(default_factory=dict)


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
                ids=bool(entry.get("ids")), origins=bool(entry.get("origins")), forwards=bool(entry.get("forwards")))


def _device(name: str, entry: dict) -> Device:
    return Device(
        name=name, node=entry["node"], roles=tuple(entry.get("roles") or ()),
        container=str(entry.get("container") or ""), rules=str(entry.get("rules") or ""),
        baseline=str(entry.get("baseline") or ""),
        files=tuple(str(path) for path in entry.get("files") or ()), reload=str(entry.get("reload") or ""), pid=str(entry.get("pid") or ""),
        names=tuple(entry.get("names") or ()),
        upstreams={str(key): str(value) for key, value in (entry.get("upstreams") or {}).items()},
        forwards={int(port): str(device) for port, device in (entry.get("forwards") or {}).items()},
    )


def wargames(source: Path) -> tuple[str, ...]:
    return tuple(sorted(path.parent.name for path in Path(source).glob(DEFINITION.format(wargame="*"))))


def read(source: Path, wargame: str) -> Definition:
    path = Path(source) / DEFINITION.format(wargame=wargame)
    if not path.is_file():
        raise RangeUnavailable(f"the wargame {wargame!r} has no topology at {path}")
    document = yaml.safe_load(path.read_text()) or {}
    found = Definition(
        wargame=wargame,
        lans={name: tuple(cidrs) for name, cidrs in (document.get("lans") or {}).items()},
        nodes={name: entry["role"] for name, entry in (document.get("nodes") or {}).items()},
        ports=tuple(_port(name, port) for name, entry in (document.get("nodes") or {}).items()
                    for port in entry.get("ports") or ()),
        devices={name: _device(name, entry) for name, entry in (document.get("devices") or {}).items()},
        watches=dict(document.get("watches") or {}),
        answers={name: str(entry["answers"]) for name, entry in (document.get("nodes") or {}).items()
                 if entry.get("answers")},
    )
    found.check()
    return found


def origin_addresses(cidr: str, count: int) -> list[str]:
    hosts = ipaddress.ip_network(cidr).hosts()
    return [str(address) for _, address in zip(range(SKIPPED_HOSTS + count), hosts)][SKIPPED_HOSTS:]


def attacker_address(origin) -> str:
    return origin_addresses(origin.subnet, 1)[0]


def customer_addresses(origins, chosen: str) -> dict[str, list[str]]:
    return {origin.id: origin_addresses(origin.subnet, origin.addresses)[1:] for origin in origins
            if origin.id != chosen and origin.addresses > 1}


def default_origin(origins, chosen: str):
    by_id = {origin.id: origin for origin in origins}
    return by_id.get(chosen) or (origins[0] if origins else None)


def internet_side(origins, chosen: str) -> str:
    origin = default_origin(origins, chosen)
    return origin_addresses(origin.subnet, 1)[0] if origin is not None else ""


def addressed(ports, origins, chosen: str) -> tuple[Port, ...]:
    placed = []
    source = internet_side(origins, chosen)
    ordered = sorted(origins, key=lambda origin: origin.id != chosen)
    for port in ports:
        if port.origins:
            extra = tuple(f"{attacker_address(origin)}/{ipaddress.ip_network(origin.subnet).prefixlen}"
                          for origin in ordered)
            port = Port(**{**vars(port), "address": source, "extra": extra})
        if port.origins or port.forwards:
            port = Port(**{**vars(port), "pairs": (EVERYWHERE,)})
        placed.append(port)
    return tuple(placed)


class _Wired:
    def __init__(self, definition: Definition, ports: tuple[Port, ...]):
        self.definition, self.ports = definition, ports

    def of(self, role: str) -> list[Port]:
        device = self.definition.filling(role).name
        return [port for port in self.ports if port.device == device]

    def facing(self, role: str, peer: str) -> str:
        for port in self.of(peer):
            if any(own.lan == port.lan for own in self.of(role)):
                return port.address
        raise RangeUnavailable(f"{role} and {peer} share no LAN in {self.definition.wargame}'s topology")

    def upstreams(self) -> dict[str, str]:
        return {f"{wargame.upper()}_ADDRESS": address
                for wargame, address in sorted(self.definition.filling("gateway").upstreams.items())}


def environment(definition: Definition, ports: tuple[Port, ...], role: str, slot: int, upstream: str,
                collector: str, customers: tuple[str, ...] = ()) -> dict[str, str]:
    wired = _Wired(definition, ports)
    if role == "kali":
        [internet] = [port for port in wired.of("attacker") if port.origins]
        return {"INTERNET_ADDRESS": internet.address, "ORIGINS": " ".join(internet.extra)}
    if role == "waf":
        return {"GATEWAY": wired.facing("gateway", "edge"), "LOG_SERVER": wired.of("log-server")[0].address,
                "WARGAMES": definition.wargame, **wired.upstreams()}
    if role == "infra":
        edge = definition.filling("edge")
        [front] = [wired.facing("edge", definition.devices[device].roles[0]) for device in edge.forwards.values()]
        return {"SLOT": str(slot), "WAF_FRONT": front, "UPSTREAM": upstream,
                "IDS_LEGS": " ".join(port.address for port in ports if port.ids),
                "LOG_SERVER": wired.of("log-server")[0].address, "COLLECTOR": collector,
                "SITES": " ".join(definition.filling("gateway").names), "CUSTOMERS": " ".join(customers)}
    return {"WARGAMES": definition.wargame, **wired.upstreams()}


def slot_env(values: dict[str, str]) -> str:
    return "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())


def booted(role: str, tag: str = "", answers: str = "") -> str:
    units = " ".join(BOOTS[role])
    answered = (f" && for _ in $(seq {ANSWER_WAIT}); do {answers} >/dev/null 2>&1 && break; sleep 1; done"
                f" && {answers}" if answers else "")
    images = f"grep -h ' image: ' {WARGAME_COMPOSE}"
    tagged = (f"{images} >/dev/null && ! {images} | grep -v -e ':{tag}$' -e '@sha256:[0-9a-f]*$' && "
              if role == "target" and tag else "")
    shown = f"echo 'the slot asks for wargame images at {tag}:'; {images}; " if tagged else ""
    return (f"install -d -m 0755 {STATE}; if {tagged}systemctl start {units}{answered}; then touch {READY}; "
            f"else {{ {shown}systemctl --no-pager --lines=20 status {units}; }} > {FAILED} 2>&1; touch {FAILED}; fi")


def managed_by(user: str, key: str) -> list:
    return ["default", {"name": user, "shell": "/bin/bash", "sudo": SUDO, "lock_passwd": True,
                        "ssh_authorized_keys": [key]}]


def user_data(node: str, role: str, env: dict[str, str], collector: str, manager: tuple[str, str] = ("", ""),
              tag: str = "", answers: str = "") -> str:
    document = {"users": managed_by(*manager)} if all(manager) else {}
    document["hostname"] = node.removeprefix("cr-")
    document["write_files"] = [
        {"path": SLOT_ENV, "permissions": "0644", "content": slot_env(env)},
        {"path": TIMESYNCD, "permissions": "0644", "content": timesyncd(collector)},
    ]
    document["runcmd"] = [["sh", "-c", booted(role, tag, answers)]]
    text = "#cloud-config\n" + yaml.safe_dump(document, sort_keys=False, width=1 << 16)
    encoded = len(base64.b64encode(text.encode()))
    if encoded > USER_DATA_LIMIT:
        raise RangeUnavailable(f"{node} needs {encoded} bytes of user data and Nova takes at most {USER_DATA_LIMIT}")
    return text


def plan(definition: Definition, slot: int, origins, chosen_origin: str, collector: str,
         manager: tuple[str, str] = ("", ""), tag: str = "") -> Sandbox:
    if not origins:
        raise RangeUnavailable("the declaration names no origin, so Kali would stand on no Internet address")
    first = default_origin(origins, chosen_origin)
    lans = tuple(Lan(name=name, cidrs=tuple(cidrs) + (
        (first.subnet,) if any(port.origins and port.lan == name for port in definition.ports) else ()))
        for name, cidrs in definition.lans.items())
    ports = addressed(definition.ports, origins, chosen_origin)
    upstream = internet_side(origins, chosen_origin)
    customers = tuple(address for held in customer_addresses(origins, chosen_origin).values() for address in held)
    nodes = []
    for name, role in definition.nodes.items():
        env = environment(definition, ports, role, slot, upstream, collector, customers)
        nodes.append(Node(name=name, role=role, ports=tuple(port for port in ports if port.node == name),
                          user_data=user_data(name, role, env, collector, manager, tag,
                                              definition.answers.get(name, "")), env=env))
    logged = next(port.lan for port in ports if port.device == definition.filling("log-server").name)
    return Sandbox(slot=slot, wargame=definition.wargame, lans=lans, nodes=tuple(nodes), logged=logged)
