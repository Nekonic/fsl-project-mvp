from __future__ import annotations

import shlex
import subprocess
import tempfile
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path

from bots.tools import SHELL

DEFAULT_SECONDS = 120
LONGEST_OUTPUT = 20000
SSH_FAILED = 255
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ConnectTimeout=20")


@dataclass
class Grant:
    scratch: tempfile.TemporaryDirectory
    ssh: dict

    @property
    def key(self) -> Path:
        return Path(self.scratch.name) / "key"

    @property
    def known_hosts(self) -> Path:
        return Path(self.scratch.name) / "known_hosts"


OPEN: dict[Hashable, Grant] = {}


def granted(ssh: dict) -> Grant:
    for field in ("host", "port", "user", "private_key", "target_host", "target_user"):
        if not ssh.get(field):
            raise KeyError(field)
    grant = Grant(tempfile.TemporaryDirectory(prefix="cr-shell-"), ssh)
    grant.key.touch(mode=0o600)
    grant.key.write_text(ssh["private_key"].rstrip("\n") + "\n")
    return grant


def ssh_command(grant: Grant, command: str) -> list[str]:
    ssh = grant.ssh
    options = [*SSH_OPTIONS, "-o", f"UserKnownHostsFile={grant.known_hosts}", "-i", str(grant.key)]
    jump = shlex.join(["ssh", *options, "-p", str(ssh["port"]), "-W", "%h:%p", f"{ssh['user']}@{ssh['host']}"])
    return ["ssh", *options, "-o", f"ProxyCommand={jump}", f"{ssh['target_user']}@{ssh['target_host']}", command]


def tail(text) -> str:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    text = text or ""
    return text if len(text) <= LONGEST_OUTPUT else text[-LONGEST_OUTPUT:]


def refused(code: str, message: str) -> dict:
    return {"operation": SHELL, "ok": False, "status": None, "local": True,
            "errors": [{"path": "", "code": code, "message": message}]}


def opened_for(holder: Hashable, open_grant: Callable[[], dict]) -> Grant | dict:
    if holder in OPEN:
        return OPEN[holder]
    answer = open_grant()
    if not answer.get("ok"):
        return {**answer, "operation": SHELL}
    try:
        grant = granted((answer.get("body") or {}).get("ssh") or {})
    except (KeyError, TypeError, AttributeError):
        return {"operation": SHELL, "ok": False, "status": answer.get("status"), "body": answer.get("body")}
    OPEN[holder] = grant
    return grant


def run(holder: Hashable, arguments: dict, open_grant: Callable[[], dict]) -> dict:
    grant = opened_for(holder, open_grant)
    if isinstance(grant, dict):
        return grant
    seconds = arguments.get("timeout") or DEFAULT_SECONDS
    try:
        ran = subprocess.run(ssh_command(grant, arguments["command"]), capture_output=True, text=True, timeout=seconds,
                     stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as late:
        return {"operation": SHELL, "ok": False, "exit_code": None, "timed_out": True,
                "stdout": tail(late.stdout), "stderr": tail(late.stderr)}
    except OSError as missing:
        return refused("ssh_unavailable", f"ssh could not run here: {missing}")
    if ran.returncode == SSH_FAILED:
        OPEN.pop(holder, None)
    return {"operation": SHELL, "ok": ran.returncode == 0, "exit_code": ran.returncode,
            "stdout": tail(ran.stdout), "stderr": tail(ran.stderr)}
