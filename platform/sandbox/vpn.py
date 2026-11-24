from __future__ import annotations

import base64
import ipaddress
import json
import os
import secrets
import selectors
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cr.config import VpnConfig, configured
from sandbox import stack_plan

KALI_PORT = 51820
MTU = 1360
KEEPALIVE = 25
PORT_MAP = "ports.json"
FIELD = 2 ** 255 - 19
A24 = 121665
BASE_POINT = (9).to_bytes(32, "little")
DATAGRAM = 65535
MAP_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class KeyPair:
    private: str
    public: str


@dataclass(frozen=True)
class Profile:
    private_key: str
    address: str
    server_public_key: str
    endpoint: str
    allowed: tuple[str, ...]


def _scalar_mult(scalar: bytes, point: bytes) -> bytes:
    clamped = bytearray(scalar)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    k = int.from_bytes(clamped, "little")
    x1 = int.from_bytes(point, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for bit_index in reversed(range(255)):
        bit = (k >> bit_index) & 1
        if swap ^ bit:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2 + z2) % FIELD, (x2 - z2) % FIELD
        aa, bb = a * a % FIELD, b * b % FIELD
        e = (aa - bb) % FIELD
        c, d = (x3 + z3) % FIELD, (x3 - z3) % FIELD
        da, cb = d * a % FIELD, c * b % FIELD
        x3 = (da + cb) ** 2 % FIELD
        z3 = x1 * (da - cb) ** 2 % FIELD
        x2 = aa * bb % FIELD
        z2 = e * (aa + A24 * e) % FIELD
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, FIELD - 2, FIELD) % FIELD).to_bytes(32, "little")


def public_key(private: str) -> str:
    return base64.b64encode(_scalar_mult(base64.b64decode(private), BASE_POINT)).decode()


def key_pair() -> KeyPair:
    raw = bytearray(secrets.token_bytes(32))
    raw[0] &= 248
    raw[31] &= 127
    raw[31] |= 64
    private = base64.b64encode(bytes(raw)).decode()
    return KeyPair(private=private, public=public_key(private))


def ports(config: VpnConfig) -> range:
    return range(config.first_port, config.last_port + 1)


def address_for(port: int, config: VpnConfig) -> str:
    network = ipaddress.ip_network(config.network)
    return str(network.network_address + 2 + (port - config.first_port))


def kali_address(config: VpnConfig) -> str:
    return str(ipaddress.ip_network(config.network).network_address + 1)


def kali_interface(config: VpnConfig) -> str:
    return f"{kali_address(config)}/{ipaddress.ip_network(config.network).prefixlen}"


def named_targets(source: Path) -> dict[str, tuple[str, ...]]:
    found: dict[str, set[str]] = {}
    for wargame in stack_plan.wargames(source):
        definition = stack_plan.read(source, wargame)
        outside = {port.lan for port in definition.ports if port.origins}
        way_in = definition.filling("edge").name
        names = set(definition.filling("gateway").names)
        for port in definition.ports:
            if port.device == way_in and port.lan in outside and port.address:
                found.setdefault(port.address, set()).update(names)
    return {address: tuple(sorted(found[address])) for address in sorted(found, key=ipaddress.ip_address)}


def target_addresses(source: Path) -> tuple[str, ...]:
    return tuple(named_targets(source))


def hosts_lines(source: Path) -> tuple[str, ...]:
    return tuple(" ".join((address, *names)) for address, names in named_targets(source).items() if names)


def profile_text(profile: Profile) -> str:
    allowed = ", ".join(f"{address}/32" for address in profile.allowed)
    return (
        "[Interface]\n"
        f"PrivateKey = {profile.private_key}\n"
        f"Address = {profile.address}/32\n"
        f"MTU = {MTU}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {profile.server_public_key}\n"
        f"Endpoint = {profile.endpoint}\n"
        f"AllowedIPs = {allowed}\n"
        f"PersistentKeepalive = {KEEPALIVE}\n"
    )


def profile_for(private_key: str, port: int, server_public_key: str, host: str, source: Path,
                config: VpnConfig) -> Profile:
    return Profile(private_key=private_key, address=address_for(port, config), server_public_key=server_public_key,
                   endpoint=f"{host}:{port}", allowed=(*target_addresses(source), kali_address(config)))


def map_path(config: VpnConfig) -> Path:
    return Path(config.directory) / PORT_MAP


def write_port_map(attached: dict[int, str], config: VpnConfig) -> None:
    folder = Path(config.directory)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=folder, delete=False, suffix=".tmp") as written:
        json.dump({str(port): address for port, address in sorted(attached.items())}, written)
    os.replace(written.name, map_path(config))


def read_port_map(config: VpnConfig) -> dict[int, str]:
    try:
        held = json.loads(map_path(config).read_text())
    except (OSError, ValueError):
        return {}
    return {int(port): str(address) for port, address in held.items() if int(port) in ports(config)}


class Relay:
    def __init__(self, config: VpnConfig):
        self.config = config
        self.selector = selectors.DefaultSelector()
        self.legs: dict[int, tuple[socket.socket, socket.socket, str]] = {}
        self.clients: dict[int, tuple] = {}
        self.seen = -1.0

    def open(self, port: int, kali: str) -> None:
        listening = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listening.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listening.bind(("0.0.0.0", port))
        upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        upstream.connect((kali, KALI_PORT))
        listening.setblocking(False)
        upstream.setblocking(False)
        self.selector.register(listening, selectors.EVENT_READ, (port, "in"))
        self.selector.register(upstream, selectors.EVENT_READ, (port, "out"))
        self.legs[port] = (listening, upstream, kali)

    def close(self, port: int) -> None:
        listening, upstream, _ = self.legs.pop(port)
        self.clients.pop(port, None)
        for leg in (listening, upstream):
            self.selector.unregister(leg)
            leg.close()

    def follow(self, wanted: dict[int, str]) -> None:
        for port in [port for port, leg in self.legs.items() if wanted.get(port) != leg[2]]:
            self.close(port)
        for port, kali in wanted.items():
            if port not in self.legs:
                try:
                    self.open(port, kali)
                except OSError as failed:
                    print(f"vpn relay: port {port} to {kali}: {failed}", file=sys.stderr, flush=True)

    def reload(self) -> None:
        try:
            changed = map_path(self.config).stat().st_mtime
        except OSError:
            changed = 0.0
        if changed != self.seen:
            self.seen = changed
            self.follow(read_port_map(self.config))

    def pass_on(self, port: int, direction: str) -> None:
        listening, upstream, _ = self.legs[port]
        try:
            if direction == "in":
                datagram, sender = listening.recvfrom(DATAGRAM)
                self.clients[port] = sender
                upstream.send(datagram)
            else:
                datagram = upstream.recv(DATAGRAM)
                if port in self.clients:
                    listening.sendto(datagram, self.clients[port])
        except OSError:
            return

    def serve(self) -> None:
        polled = 0.0
        while True:
            if time.monotonic() - polled >= MAP_POLL_SECONDS:
                self.reload()
                polled = time.monotonic()
            if not self.legs:
                time.sleep(MAP_POLL_SECONDS)
                continue
            for ready, _ in self.selector.select(MAP_POLL_SECONDS):
                port, direction = ready.data
                if port in self.legs:
                    self.pass_on(port, direction)


def relay(config: VpnConfig | None = None) -> None:
    Relay(config or configured().vpn).serve()
