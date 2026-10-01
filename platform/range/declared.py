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
class Origin:
    id: str
    label: str
    country: str
    subnet: str
    share: float
    addresses: int
    segment: str

@dataclass(frozen=True)
class Host:
    setup: str
    files: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    names: tuple[str, ...] = ()

@dataclass(frozen=True)
class Declaration:
    segments: tuple[Segment, ...] = ()
    origins: tuple[Origin, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    watches: dict[str, str] = field(default_factory=dict)
    hosts: dict[str, Host] = field(default_factory=dict)
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
        roleless = sorted(set(self.hosts) - set(self.roles.values()))
        if roleless:
            raise ValueError(
                f"{', '.join(roleless)} would be built as an image and no role "
                f"names it, so nothing in the range would ever reach it"
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

def _origins(entry) -> tuple[Origin, ...]:
    return tuple(
        Origin(
            id=origin["id"],
            label=origin["label"],
            country=origin["country"],
            subnet=origin["subnet"],
            share=float(origin["share"]),
            addresses=int(origin["addresses"]),
            segment=entry["id"],
        )
        for origin in entry.get("origins") or []
    )

def _segments(entry, origins: tuple[Origin, ...]) -> tuple[Segment, ...]:
    name = entry.get("name") or entry["id"]
    if origins:
        return tuple(Segment(id=o.id, name=name, origin=o.label) for o in origins)
    return (Segment(id=entry["id"], name=name, origin=entry.get("origin") or ""),)

def _hosts(entries) -> dict[str, Host]:
    return {
        name: Host(
            setup=entry["setup"],
            files=tuple(entry.get("files") or ()),
            segments=tuple(entry.get("segments") or ()),
            names=tuple(entry.get("names") or ()),
        )
        for name, entry in (entries or {}).items()
    }

def read(path: Path = DECLARATION) -> Declaration:
    document = yaml.safe_load(Path(path).read_text()) or {}
    entries = document.get("segments") or []
    origins = {entry["id"]: _origins(entry) for entry in entries}
    found = Declaration(
        segments=tuple(
            segment
            for entry in entries
            for segment in _segments(entry, origins[entry["id"]])
        ),
        origins=tuple(origin for entry in entries for origin in origins[entry["id"]]),
        roles=dict(document.get("roles") or {}),
        watches=dict(document.get("watches") or {}),
        hosts=_hosts(document.get("hosts")),
        default_origin=document.get("default_origin") or "",
        defended_site=_site(document.get("defended_site")),
    )
    found.check()
    return found
