from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta

from cr.config import BoxConfig
from cr.errors import NotFound
from sandbox.runner import RangeUnavailable

ATTACKER_ROLE = "attacker"
RUNS = "/var/lib/cr-runs"
OUTPUT_LIMIT = 65536
RESOLUTION = timedelta(seconds=1)


class AttackerUnavailable(RangeUnavailable):
    code = "attacker_unavailable"


class UnknownOrigin(NotFound):
    code = "unknown_origin"


@dataclass(frozen=True)
class Command:
    at: datetime
    marker: str
    text: str


@dataclass(frozen=True)
class RunOutput:
    output: str
    offset: int
    done: bool
    exit_code: int | None


def origins(described, config: BoxConfig) -> list[dict]:
    box = config.proxy
    terminal = config.attacker

    standing = [
        (segment, {node.name: node.address for node in segment.nodes})
        for segment in described.segments
        if any(node.name == box for node in segment.nodes)
    ]
    if not standing:
        raise AttackerUnavailable(f"{box} is on no network at all")

    found = [
        {
            "id": segment.id,
            "network": segment.network,
            "label": segment.origin,
            "subnet": segment.subnet,
            "source_ip": addresses[box],
            "direct_ip": addresses.get(terminal, ""),
            "address": addresses.get(config.way_in) or segment.gateway,
            "target_url": config.target_url,
            "default": segment.id == config.default_origin,
        }
        for segment, addresses in standing
        if segment.origin and addresses.get(box)
    ]
    return sorted(found, key=lambda origin: origin["id"])


def find(described, origin_id: str | None, config: BoxConfig) -> dict:
    available = origins(described, config)
    if not origin_id:
        if not available:
            raise UnknownOrigin("the stack offers no origin to attack from")
        return next((o for o in available if o["default"]), available[0])
    for origin in available:
        if origin["id"] == origin_id:
            return origin
    raise UnknownOrigin(
        f"no origin {origin_id!r}; the stack offers "
        f"{[o['id'] for o in available]}"
    )


def kali_address(adapter) -> str:
    return adapter.address(ATTACKER_ROLE)


def launch_with(launcher, config: BoxConfig):
    def launch(argv: list[str], timeout: float = 600.0):
        return launcher(config.tool_image, argv, timeout=timeout)

    return launch


def commands(box, config: BoxConfig) -> list[Command]:
    ran = box(["cat", config.command_log])
    if not ran.ok:
        if "No such file" in ran.output:
            return []
        raise AttackerUnavailable(f"could not read {config.command_log}: {ran.output.strip()[:200]}")
    return [record for line in ran.output.splitlines() if (record := _command(line)) is not None]


def within(typed: list[Command], start: datetime, end: datetime | None) -> list[Command]:
    opened = start.replace(microsecond=0)
    closed = None if end is None else end.replace(microsecond=0) + RESOLUTION
    return [command for command in typed if command.at >= opened and (closed is None or command.at < closed)]


def _command(line: str) -> Command | None:
    stamp, _, rest = line.partition("\t")
    marker, tab, text = rest.partition("\t")
    if not tab or not text:
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return Command(at=at, marker=marker, text=text)


def _run_dir(run_id: int) -> str:
    return f"{RUNS}/{int(run_id)}"


def start_run(box, run_id: int, argv: list[str]) -> None:
    folder = _run_dir(run_id)
    _ran(box, (
        f"set -e; rm -rf {folder}; mkdir -p {folder}; cd {folder}; "
        f"setsid nohup sh -c '\"$@\" >{folder}/output 2>&1; echo $? > {folder}/exit' sh {shlex.join(argv)} "
        f"</dev/null >/dev/null 2>&1 & echo $! > {folder}/pid"
    ), f"start run {run_id}")


def run_output(box, run_id: int, offset: int = 0, limit: int = OUTPUT_LIMIT) -> RunOutput:
    folder = _run_dir(run_id)
    said = _ran(box, (
        f"[ -d {folder} ] || {{ echo cr.run=missing; exit 0; }}; "
        f"cat {folder}/exit 2>/dev/null | sed 's/^/cr.exit=/'; printf 'cr.output=\\n'; "
        f"tail -c +{int(offset) + 1} {folder}/output 2>/dev/null | head -c {int(limit)}"
    ), f"hand over run {run_id}").output
    if said.startswith("cr.run=missing"):
        raise NotFound(f"no run {run_id} on the box", code="unknown_run")
    head, _, output = said.partition("cr.output=\n")
    exit_line = next((line for line in head.splitlines() if line.startswith("cr.exit=")), "")
    code = exit_line.removeprefix("cr.exit=").strip()
    return RunOutput(output=output, offset=int(offset) + len(output.encode()), done=bool(exit_line),
                     exit_code=int(code) if code.lstrip("-").isdigit() else None)


def stop_run(box, run_id: int) -> None:
    folder = _run_dir(run_id)
    _ran(box, (
        f"[ -f {folder}/pid ] || exit 0; pid=$(cat {folder}/pid); "
        f"kill -TERM -- -$pid 2>/dev/null || kill -TERM $pid 2>/dev/null || true; "
        f"[ -f {folder}/exit ] || echo 143 > {folder}/exit"
    ), f"stop run {run_id}")


def wear_origin(chosen: dict, box) -> None:
    ran = box(["sudo", "/usr/local/sbin/set-origin", chosen["source_ip"]])
    if not ran.ok:
        raise AttackerUnavailable(
            f"the box could not wear {chosen['source_ip']}: {ran.output.strip()[:200]}"
        )

def attach_peer(box, server_private_key: str, peer_public_key: str, peer_address: str, own_address: str) -> None:
    ran = box(["sudo", "/usr/local/sbin/set-peer", peer_public_key, f"{peer_address}/32", own_address],
              stdin=server_private_key)
    if not ran.ok:
        raise AttackerUnavailable(f"the box could not take the learner's tunnel: {ran.output.strip()[:200]}")


def detach_peer(box) -> None:
    ran = box(["sudo", "/usr/local/sbin/set-peer"])
    if not ran.ok:
        raise AttackerUnavailable(f"the box could not drop the learner's tunnel: {ran.output.strip()[:200]}")


SQLMAP_RUNS = "/tmp/sqlmap-runs"


def _as_root(script: str) -> list[str]:
    return ["sudo", "sh", "-c", script]

def _ran(box, script: str, what: str, stdin: str | None = None, timeout: float = 60.0):
    ran = box(_as_root(script), stdin=stdin, timeout=timeout)
    if not ran.ok:
        raise AttackerUnavailable(f"the box could not {what}: {ran.output.strip()[-300:]}")
    return ran

LEARNER_ACCOUNT = "kali"
