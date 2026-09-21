from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from range.ports import RangeUnavailable, Segment

DECLARATION = Path(__file__).resolve().parent / "declaration.yaml"

@dataclass(frozen=True)
class Declaration:
    segments: tuple[Segment, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    watches: dict[str, str] = field(default_factory=dict)
    default_origin: str = ""

    def check(self) -> None:
        for sensing, sensed in self.watches.items():
            missing = [r for r in (sensing, sensed) if r not in self.roles]
            if missing:
                raise ValueError(
                    f"{sensing!r} is declared to watch {sensed!r} and nothing "
                    f"fills {', '.join(sorted(missing))}"
                )
        outside = {s.id for s in self.segments if s.outside}
        if self.default_origin and self.default_origin not in outside:
            raise ValueError(
                f"default_origin is {self.default_origin!r}, which is not a "
                f"segment an attack can start from. Outside: {sorted(outside)}"
            )

    def segment(self, segment_id: str) -> Segment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise RangeUnavailable(
            f"the range has a segment {segment_id!r} that the declaration does "
            f"not name, so the console would draw it with no name and no "
            f"origin. Declared: {sorted(s.id for s in self.segments)}"
        )

def read(path: Path = DECLARATION) -> Declaration:
    document = yaml.safe_load(Path(path).read_text()) or {}
    found = Declaration(
        segments=tuple(
            Segment(
                id=entry["id"],
                name=entry.get("name") or entry["id"],
                origin=entry.get("origin") or "",
            )
            for entry in document.get("segments") or []
        ),
        roles=dict(document.get("roles") or {}),
        watches=dict(document.get("watches") or {}),
        default_origin=document.get("default_origin") or "",
    )
    found.check()
    return found
