from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

class RangeUnavailable(RuntimeError):
    """The substrate could not be reached, so nothing is known about the range.

    Distinct from a command that ran and failed. A caller that confuses the two
    records its own breakage as a result about the defence.
    """

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
        """Run argv on the host this runner is bound to.

        Returns Ran when the command ran, whatever it exited with. Raises
        RangeUnavailable when it could not be dispatched at all.
        """

class Launcher(Protocol):
    def __call__(
        self, image: str, argv: list[str], timeout: float = 600.0
    ) -> Ran:
        """Start a throwaway host from image on the segment this is bound to.

        Returns when it has finished. Raises RangeUnavailable when nothing
        could be started at all.
        """

class Substrate(Protocol):
    def describe(self) -> Shape:
        """The range as it is now. Raises RangeUnavailable rather than guessing."""

    def runner(self, role: str, segment_id: str = "") -> Runner:
        """A Runner bound to the host filling that role, on that segment."""

    def launcher(self, segment_id: str) -> Launcher:
        """A Launcher that starts throwaway hosts on that segment."""
