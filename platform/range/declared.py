from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from range.ports import RangeUnavailable, Segment

DECLARATION = Path(__file__).resolve().parent / "declaration.yaml"

@dataclass(frozen=True)
class Site:
    label: str
    lat: float
    lon: float

@dataclass(frozen=True)
class Declaration:
    segments: tuple[Segment, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    watches: dict[str, str] = field(default_factory=dict)
    default_origin: str = ""
    defended_site: Site | None = None

    def check(self) -> None:
        site = self.defended_site
        if site and not (-90 <= site.lat <= 90 and -180 <= site.lon <= 180):
            raise ValueError(
                f"defended_site {site.label!r} is at lat {site.lat}, lon "
                f"{site.lon}, which is not on the globe"
            )
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

    def host(self, role: str) -> str:
        host = self.roles.get(role)
        if host is None:
            raise RangeUnavailable(f"no host fills the role {role!r}")
        return host

    def watching(self) -> list[tuple[str, str]]:
        return [
            (self.roles[sensing], self.roles[sensed])
            for sensing, sensed in sorted(self.watches.items())
        ]

    def segment(self, segment_id: str) -> Segment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise RangeUnavailable(
            f"the range has a segment {segment_id!r} that the declaration does "
            f"not name, so the console would draw it with no name and no "
            f"origin. Declared: {sorted(s.id for s in self.segments)}"
        )

def _site(entry) -> Site | None:
    if not entry:
        return None
    return Site(label=entry["label"], lat=float(entry["lat"]), lon=float(entry["lon"]))

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
        defended_site=_site(document.get("defended_site")),
    )
    found.check()
    return found
