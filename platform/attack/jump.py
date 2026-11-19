from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from cr.config import JumpConfig
from range.runner import RangeUnavailable

KALI_SSH_PORT = 22
KALI_USER = "kali"
JUMP_USER = "jump"
KEYS_READER = "cr"
KEY_NAME = "cr-session-{}"
PUBLIC_KEY = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}")
GRANT = re.compile(
    r'restrict,port-forwarding,permitopen="(?P<kali>[0-9.]+):(?P<port>\d+)" '
    r"(?P<key>ssh-ed25519 [A-Za-z0-9+/]+={0,2}) cr-session-(?P<seat>\d+)"
)
_WRITING = threading.Lock()

@dataclass(frozen=True)
class Grant:
    seat_id: int
    kali: str
    public_key: str

    @property
    def name(self) -> str:
        return key_name(self.seat_id)

    @property
    def line(self) -> str:
        return authorized_keys_line(self.public_key, self.kali, self.seat_id)

    @property
    def fingerprint(self) -> str:
        blob = base64.b64decode(self.public_key.split()[1])
        return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")

@dataclass(frozen=True)
class Issued:
    grant: Grant
    private_key: str

def key_name(seat_id: int) -> str:
    return KEY_NAME.format(int(seat_id))

def kali_address(given: str) -> str:
    try:
        return str(ipaddress.IPv4Address(given))
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise RangeUnavailable(f"the seat's Kali has no management address to forward to: {given!r}") from exc

def authorized_keys_line(public_key: str, kali: str, seat_id: int) -> str:
    if not PUBLIC_KEY.fullmatch(public_key):
        raise ValueError(f"not one ed25519 public key: {public_key[:80]!r}")
    return (f'restrict,port-forwarding,permitopen="{kali_address(kali)}:{KALI_SSH_PORT}" '
            f"{public_key} {key_name(seat_id)}")

def keys_file(config: JumpConfig) -> Path:
    return Path(config.directory) / "authorized_keys"

def host_key(config: JumpConfig) -> Path:
    return Path(config.directory) / "ssh_host_ed25519_key"

def keypair(seat_id: int) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as scratch:
        made = Path(scratch) / "key"
        try:
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", key_name(seat_id), "-f", str(made)],
                check=True, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(f"ssh-keygen could not make a key: {exc}") from exc
        public = " ".join(made.with_suffix(".pub").read_text().split()[:2])
        return made.read_text(), public

def grants(config: JumpConfig) -> list[Grant]:
    try:
        lines = keys_file(config).read_text().splitlines()
    except FileNotFoundError:
        return []
    return [
        Grant(int(found["seat"]), found["kali"], found["key"])
        for line in lines if (found := GRANT.fullmatch(line.strip()))
    ]

def granted(seat_id: int, config: JumpConfig) -> Grant | None:
    return next((grant for grant in grants(config) if grant.seat_id == int(seat_id)), None)

def _keep(kept: list[Grant], config: JumpConfig) -> None:
    target = keys_file(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}")
    fresh.write_text("".join(f"{grant.line}\n" for grant in kept))
    fresh.chmod(0o600)
    fresh.replace(target)

def issue(seat_id: int, kali: str, config: JumpConfig) -> Issued:
    private, public = keypair(seat_id)
    grant = Grant(int(seat_id), kali_address(kali), public)
    with _WRITING:
        _keep([held for held in grants(config) if held.seat_id != grant.seat_id] + [grant], config)
    return Issued(grant, private)

def revoke(seat_id: int, config: JumpConfig) -> Grant | None:
    with _WRITING:
        held = grants(config)
        dropped = next((grant for grant in held if grant.seat_id == int(seat_id)), None)
        if dropped is not None:
            _keep([grant for grant in held if grant is not dropped], config)
    return dropped

def host_alias(wargame: str) -> str:
    return f"{wargame}-kali"

def ssh_config(grant: Grant, wargame: str, config: JumpConfig) -> str:
    alias = host_alias(wargame)
    identity = f"~/.ssh/{grant.name}"
    return (
        f"Host {alias}-jump\n"
        f"    HostName {config.host}\n"
        f"    Port {config.port}\n"
        f"    User {JUMP_USER}\n"
        f"    IdentityFile {identity}\n"
        f"    IdentitiesOnly yes\n"
        f"\n"
        f"Host {alias}\n"
        f"    HostName {grant.kali}\n"
        f"    User {KALI_USER}\n"
        f"    IdentityFile {identity}\n"
        f"    IdentitiesOnly yes\n"
        f"    HostKeyAlias {grant.name}-kali\n"
        f"    ProxyJump {alias}-jump\n"
    )

def shown(grant: Grant, wargame: str, config: JumpConfig) -> dict:
    return {
        "issued": True,
        "host": host_alias(wargame),
        "key_file": f"~/.ssh/{grant.name}",
        "fingerprint": grant.fingerprint,
        "config": ssh_config(grant, wargame, config),
    }

def sshd_config(config: JumpConfig) -> str:
    folder = Path(config.directory)
    return (
        f"Port {config.port}\n"
        f"HostKey {folder / 'ssh_host_ed25519_key'}\n"
        f"PidFile /run/sshd-jump.pid\n"
        f"AllowUsers {JUMP_USER}\n"
        "AuthenticationMethods publickey\n"
        "PubkeyAuthentication yes\n"
        "PasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\n"
        "PermitRootLogin no\n"
        "UsePAM no\n"
        "AuthorizedKeysFile none\n"
        f"AuthorizedKeysCommand /usr/bin/cat {folder / 'authorized_keys'}\n"
        f"AuthorizedKeysCommandUser {KEYS_READER}\n"
        "AllowTcpForwarding local\n"
        "AllowAgentForwarding no\n"
        "AllowStreamLocalForwarding no\n"
        "X11Forwarding no\n"
        "PermitTunnel no\n"
        "GatewayPorts no\n"
        "PermitTTY no\n"
        "PermitUserRC no\n"
        "ForceCommand /usr/sbin/nologin\n"
        "PrintMotd no\n"
        "MaxAuthTries 3\n"
        "LoginGraceTime 20\n"
        "ClientAliveInterval 30\n"
        "LogLevel VERBOSE\n"
    )
