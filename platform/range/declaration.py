from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from range import stack_plan
from range.runner import RangeUnavailable, Segment

DECLARATION = Path(__file__).resolve().parent / "declaration.yaml"
SOURCE = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Site:
    label: str
    lat: float
    lon: float

@dataclass(frozen=True)
class Origin:
    id: str
    label: str
    subnet: str
    addresses: int
    segment: str

@dataclass(frozen=True)
class Host:
    node: str = ""
    container: str = ""
    rules: str = ""
    reload: str = ""
    pid: str = ""
    names: tuple[str, ...] = ()

@dataclass(frozen=True)
class Declaration:
    segments: tuple[Segment, ...] = ()
    origins: tuple[Origin, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    compose: dict[str, str] = field(default_factory=dict)
    watches: dict[str, str] = field(default_factory=dict)
    hosts: dict[str, Host] = field(default_factory=dict)
    default_origin: str = ""
    defended_site: Site | None = None
    definitions: dict[str, stack_plan.Definition] = field(default_factory=dict)

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

    @property
    def wargames(self) -> tuple[str, ...]:
        return tuple(sorted(self.definitions))

    def host(self, role: str) -> str:
        host = self.roles.get(role)
        if host is None:
            raise RangeUnavailable(f"no host fills the role {role!r}")
        return host

    def node(self, role: str) -> str:
        host = self.host(role)
        node = (self.hosts.get(host) or Host()).node
        if not node:
            raise RangeUnavailable(f"{host} fills {role!r} and runs on no node of a slot")
        return node

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
            subnet=origin["subnet"],
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

def _merged(definitions: dict[str, stack_plan.Definition]) -> tuple[dict, dict, dict, dict]:
    roles, compose, hosts, watches = {}, {}, {}, {}
    for wargame, definition in sorted(definitions.items()):
        for device in definition.devices.values():
            host = Host(node=device.node, container=device.container, rules=device.rules,
                        reload=device.reload, pid=device.pid, names=device.names)
            if hosts.setdefault(device.name, host) != host:
                raise ValueError(f"{wargame}'s topology declares {device.name} unlike another wargame's")
            for role in device.roles:
                if roles.setdefault(role, device.name) != device.name:
                    raise ValueError(f"{wargame}'s topology fills {role!r} with {device.name}, another wargame's "
                                     f"with {roles[role]}")
                if device.container:
                    compose[role] = device.container
        watches.update(definition.watches)
    return roles, compose, hosts, watches

def read(path: Path = DECLARATION, source: Path | None = None) -> Declaration:
    source = Path(source or SOURCE)
    document = yaml.safe_load(Path(path).read_text()) or {}
    entries = document.get("segments") or []
    origins = {entry["id"]: _origins(entry) for entry in entries}
    definitions = {wargame: stack_plan.read(source, wargame) for wargame in stack_plan.wargames(source)}
    roles, compose, hosts, watches = _merged(definitions)
    found = Declaration(
        segments=tuple(
            segment
            for entry in entries
            for segment in _segments(entry, origins[entry["id"]])
        ),
        origins=tuple(origin for entry in entries for origin in origins[entry["id"]]),
        roles={**roles, **(document.get("roles") or {})},
        compose=compose,
        watches=watches,
        hosts=hosts,
        default_origin=document.get("default_origin") or "",
        defended_site=_site(document.get("defended_site")),
        definitions=definitions,
    )
    found.check()
    return found
