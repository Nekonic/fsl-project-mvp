from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

LOG_PATH = "/var/log/fsl/commands.log"

class OperatorLogUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class Command:
    at: datetime
    marker: str
    text: str

def commands(attacker, path: str = LOG_PATH) -> list[Command]:
    ran = attacker(["cat", path])
    if not ran.ok:
        if "No such file" in ran.output:
            return []
        raise OperatorLogUnavailable(
            f"could not read {path}: {ran.output.strip()[:200]}"
        )

    return [
        record for line in ran.output.splitlines()
        if (record := _record(line)) is not None
    ]

RESOLUTION = timedelta(seconds=1)

def within(
    typed: list[Command], start: datetime, end: datetime | None
) -> list[Command]:
    opened = start.replace(microsecond=0)
    closed = None if end is None else end.replace(microsecond=0) + RESOLUTION
    return [
        command for command in typed
        if command.at >= opened and (closed is None or command.at < closed)
    ]

def _record(line: str) -> Command | None:
    stamp, _, rest = line.partition("\t")
    marker, tab, text = rest.partition("\t")
    if not tab or not text:
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return Command(at=at, marker=marker, text=text)
