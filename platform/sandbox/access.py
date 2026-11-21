from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import shlex
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from cr.config import JumpConfig, build
from sandbox.runner import RangeUnavailable, Runner

BOX_SSH_PORT = 22
JUMP_USER = "jump"
KEYS_READER = "cr"
KEY_NAME = "cr-session-{}"
BOX_NAME = re.compile(r"[a-z]*")
KEY_NAME_SHAPE = re.compile(r"[a-z0-9-]+")
PUBLIC_KEY = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}")
GRANT = re.compile(
    r'restrict,port-forwarding,permitopen="(?P<address>[0-9.]+):(?P<port>\d+)" '
    r"(?P<key>ssh-ed25519 [A-Za-z0-9+/]+={0,2}) cr-session-(?P<player>\d+)(?:-(?P<box>[a-z]+))?"
)
_WRITING = threading.Lock()


@dataclass(frozen=True)
class Grant:
    player_id: int
    address: str
    public_key: str
    box: str = ""

    @property
    def name(self) -> str:
        return key_name(self.player_id, self.box)

    @property
    def line(self) -> str:
        return authorized_keys_line(self.public_key, self.address, self.player_id, self.box)

    @property
    def fingerprint(self) -> str:
        blob = base64.b64decode(self.public_key.split()[1])
        return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


@dataclass(frozen=True)
class Issued:
    grant: Grant
    private_key: str


@dataclass(frozen=True)
class Access:
    host: str
    port: int
    user: str
    private_key: str
    target_host: str
    target_user: str


def key_name(player_id: int, box: str = "") -> str:
    if not BOX_NAME.fullmatch(box):
        raise ValueError(f"a box name is lower-case letters, got {box!r}")
    return KEY_NAME.format(int(player_id)) + (f"-{box}" if box else "")


def box_address(given: str) -> str:
    try:
        return str(ipaddress.IPv4Address(given))
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise RangeUnavailable(f"the player's box has no management address to forward to: {given!r}") from exc


def authorized_keys_line(public_key: str, address: str, player_id: int, box: str = "") -> str:
    if not PUBLIC_KEY.fullmatch(public_key):
        raise ValueError(f"not one ed25519 public key: {public_key[:80]!r}")
    return (f'restrict,port-forwarding,permitopen="{box_address(address)}:{BOX_SSH_PORT}" '
            f"{public_key} {key_name(player_id, box)}")


def keys_file(config: JumpConfig) -> Path:
    return Path(config.directory) / "authorized_keys"


def keypair(player_id: int, box: str = "") -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as scratch:
        made = Path(scratch) / "key"
        try:
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", key_name(player_id, box), "-f", str(made)],
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
        Grant(int(found["player"]), found["address"], found["key"], found["box"] or "")
        for line in lines if (found := GRANT.fullmatch(line.strip()))
    ]


def granted(player_id: int, config: JumpConfig, box: str = "") -> Grant | None:
    return next((grant for grant in grants(config) if grant.player_id == int(player_id) and grant.box == box), None)


def kept(held: list[Grant], config: JumpConfig) -> None:
    target = keys_file(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}")
    fresh.write_text("".join(f"{grant.line}\n" for grant in held))
    fresh.chmod(0o600)
    fresh.replace(target)


def issue(player_id: int, address: str, config: JumpConfig, box: str = "") -> Issued:
    private, public = keypair(player_id, box)
    grant = Grant(int(player_id), box_address(address), public, box)
    with _WRITING:
        kept([held for held in grants(config) if held.name != grant.name] + [grant], config)
    return Issued(grant, private)


def revoke(player_id: int, config: JumpConfig, box: str = "") -> Grant | None:
    with _WRITING:
        held = grants(config)
        dropped = next((grant for grant in held if grant.name == key_name(player_id, box)), None)
        if dropped is not None:
            kept([grant for grant in held if grant is not dropped], config)
    return dropped


def account_keys(account: str) -> str:
    who = shlex.quote(account)
    return (
        f"home=\"$(getent passwd {who} | cut -d: -f6)\"; [ -n \"$home\" ]; "
        f"install -d -m 0700 -o {who} -g {who} \"$home/.ssh\"; "
        "keys=\"$home/.ssh/authorized_keys\"; touch \"$keys\"; "
    )


def without(name: str) -> str:
    if not KEY_NAME_SHAPE.fullmatch(name):
        raise ValueError(f"a key name is lower-case letters, digits and dashes, got {name!r}")
    return f"grep -v -e ' {name}$' \"$keys\" > \"$keys.new\" || true; "


def keys_kept(account: str) -> str:
    return f"chown {shlex.quote(account)}: \"$keys.new\"; chmod 0600 \"$keys.new\"; mv \"$keys.new\" \"$keys\""


def as_root(box: Runner, script: str, what: str, stdin: str | None = None) -> None:
    ran = box(["sudo", "sh", "-c", script], stdin=stdin, timeout=60.0)
    if not ran.ok:
        raise RangeUnavailable(f"the box could not {what}: {ran.output.strip()[-300:]}")


def authorize_key(box: Runner, public_key: str, name: str, account: str) -> None:
    as_root(box, "set -e; umask 077; " + account_keys(account) + without(name)
            + "cat >> \"$keys.new\"; " + keys_kept(account),
            f"take the key {name} for {account}", stdin=f"{public_key} {name}\n")


def drop_key(box: Runner, name: str, account: str) -> None:
    as_root(box, "set -e; umask 077; " + account_keys(account) + without(name) + keys_kept(account),
            f"drop the key {name} for {account}")


def account_ended(account: str) -> str:
    who = shlex.quote(account)
    return (
        f"set -u; id -u {who} >/dev/null 2>&1 || exit 0; "
        f"crontab -r -u {who} 2>/dev/null || true; "
        f"if command -v atq >/dev/null 2>&1; then atq | awk -v who={who} '$NF == who {{print $1}}' | xargs -r atrm; fi; "
        f"loginctl disable-linger {who} 2>/dev/null || true; "
        f"loginctl terminate-user {who} 2>/dev/null || true; "
        f"for attempt in 1 2 3; do pkill -KILL -u {who} || break; sleep 1; done; "
        f"! pgrep -u {who} >/dev/null"
    )


def end_account(box: Runner, account: str) -> None:
    as_root(box, account_ended(account), f"end what {account} left running")


def open_access(player_id: int, address: str, box: Runner, account: str, config: JumpConfig,
                box_name: str = "") -> Access:
    issued = issue(player_id, address, config, box_name)
    authorize_key(box, issued.grant.public_key, issued.grant.name, account)
    return Access(host=config.host, port=config.port, user=JUMP_USER, private_key=issued.private_key,
                  target_host=issued.grant.address, target_user=account)


def close_access(player_id: int, box_of, account: str, config: JumpConfig, box_name: str = "") -> Grant | None:
    dropped = revoke(player_id, config, box_name)
    if dropped is not None:
        drop_key(box_of(), dropped.name, account)
    return dropped


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


if __name__ == "__main__":
    print(sshd_config(build().jump), end="")
