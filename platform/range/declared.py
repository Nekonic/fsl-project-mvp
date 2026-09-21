from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from range.ports import Segment

DECLARATION = Path(__file__).resolve().parent / "declaration.yaml"

@dataclass(frozen=True)
class Declaration:
    segments: tuple[Segment, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    default_origin: str = ""

    def check(self) -> None:
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
        return Segment(id=segment_id, name=segment_id)

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
        default_origin=document.get("default_origin") or "",
    )
    found.check()
    return found
