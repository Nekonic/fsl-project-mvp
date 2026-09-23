from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Protocol

EXIT_MARK = "fsl.exit="
EXIT_REPORT = f'printf "{EXIT_MARK}%d\\n" "$?" >&2'
_REPORTED = re.compile(r"(?s)(.*)" + re.escape(EXIT_MARK) + r"(\d+)\n(.*)\Z")

class RangeUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class Ran:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

@dataclass(frozen=True)
class Node:
    name: str
    address: str

@dataclass(frozen=True)
class Segment:
    id: str
    name: str
    origin: str = ""
    subnet: str = ""
    network: str = ""
    gateway: str = ""
    nodes: tuple[Node, ...] = field(default_factory=tuple)

    @property
    def outside(self) -> bool:
        return bool(self.origin)

@dataclass(frozen=True)
class Sensor:
    name: str
    watches: str

@dataclass(frozen=True)
class Shape:
    segments: tuple[Segment, ...]
    sensors: tuple[Sensor, ...]

class Runner(Protocol):
    def __call__(
        self, argv: list[str], stdin: str | None = None, timeout: float = 60.0
    ) -> Ran:
        ...

class Launcher(Protocol):
    def __call__(
        self, image: str, argv: list[str], timeout: float = 600.0
    ) -> Ran:
        ...

class Substrate(Protocol):
    def describe(self) -> Shape:
        ...

    def segments(self) -> tuple[Segment, ...]:
        ...

    def runner(self, role: str, segment_id: str = "") -> Runner:
        ...

    def launcher(self, segment_id: str) -> Launcher:
        ...

def reporting(argv: list[str]) -> list[str]:
    return ["sh", "-c", "--", f"{shlex.join(argv)}; {EXIT_REPORT}"]

def reported(stderr: str) -> tuple[int, str] | None:
    found = _REPORTED.match(stderr)
    if found is None:
        return None
    return int(found[2]), found[1] + found[3]
