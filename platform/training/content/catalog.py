from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cr.errors import ServerError
from domain.problems import CatalogCase, WargameCatalog
from training.attack.cases import load_cases

WARGAMES = "wargames"
CASES = "redteam/cases"
DECLARED = "wargame.yaml"
FIELDS = ("id", "title", "image", "public_url", "hosts", "objective_model", "case_file", "default_traffic")
OBJECTIVE_MODELS = ("loot_verified", "effect_observed")
GATEWAY = "gateway"
TIER_FIELDS = ("key", "name", "category", "difficulty")


class CatalogBroken(ServerError):
    pass


@dataclass(frozen=True)
class Case:
    name: str
    malicious: bool
    tool_case: bool
    expect: str | None = None

    @property
    def kind(self) -> str:
        return "tool" if self.tool_case else "http"


@dataclass(frozen=True)
class Objective:
    key: str
    name: str
    category: str
    difficulty: int
    rule: dict[str, Any]


@dataclass(frozen=True)
class Probes:
    image_digest: str
    recorded_at: str
    cases: dict[str, Any]


@dataclass(frozen=True)
class Wargame:
    id: str
    title: str
    image: str
    public_url: str
    hosts: tuple[str, ...]
    objective_model: str
    case_file: str
    default_traffic: str | None
    cases: tuple[Case, ...]
    objectives: tuple[Objective, ...]
    secret: dict[str, Any]
    traffic_profiles: tuple[str, ...]
    probes: Probes | None

    @property
    def recorded(self) -> frozenset[str]:
        return frozenset(self.probes.cases) if self.probes else frozenset()

    @property
    def benign_cases(self) -> tuple[str, ...]:
        return tuple(case.name for case in self.cases if not case.malicious and not case.tool_case)

    def case(self, name: str) -> Case | None:
        return next((case for case in self.cases if case.name == name), None)

    def for_validation(self) -> WargameCatalog:
        return WargameCatalog(
            cases={case.name: CatalogCase(malicious=case.malicious, recorded=case.name in self.recorded,
                                          tool_case=case.tool_case) for case in self.cases},
            objectives=frozenset(objective.key for objective in self.objectives),
        )


def wargame_ids(root: Path) -> list[str]:
    return sorted(path.parent.name for path in (root / WARGAMES).glob(f"*/{DECLARED}"))


def wargames(root: Path) -> list[Wargame]:
    return [read(root, wargame_id) for wargame_id in wargame_ids(root)]


def validation_catalog(root: Path) -> dict[str, WargameCatalog]:
    return {wargame.id: wargame.for_validation() for wargame in wargames(root)}


def read(root: Path, wargame_id: str) -> Wargame:
    folder = root / WARGAMES / wargame_id
    declared = loaded(folder / DECLARED)
    if not isinstance(declared, dict):
        raise CatalogBroken(f"{folder / DECLARED} is not a mapping")
    missing = [name for name in FIELDS if name not in declared]
    if missing:
        raise CatalogBroken(f"{folder / DECLARED} lacks {', '.join(missing)}")
    if declared["id"] != wargame_id:
        raise CatalogBroken(f"{folder / DECLARED} names id {declared['id']!r} in folder {wargame_id!r}")
    if declared["objective_model"] not in OBJECTIVE_MODELS:
        raise CatalogBroken(f"{folder / DECLARED} objective_model must be one of {OBJECTIVE_MODELS}")
    hosts = tuple(declared["hosts"] or ())
    served = gateway_names(folder)
    if not hosts or not set(hosts) <= served:
        raise CatalogBroken(f"{folder / DECLARED} hosts {hosts} are not all served by the topology's gateway")
    profiles = traffic_profiles(folder)
    if declared["default_traffic"] is not None and declared["default_traffic"] not in profiles:
        raise CatalogBroken(f"{folder / DECLARED} default_traffic {declared['default_traffic']!r} is not a profile")
    cases = read_cases(root / CASES / declared["case_file"])
    return Wargame(
        id=wargame_id, title=str(declared["title"]), image=str(declared["image"]),
        public_url=str(declared["public_url"]), hosts=hosts, objective_model=declared["objective_model"],
        case_file=declared["case_file"], default_traffic=declared["default_traffic"], cases=cases,
        objectives=read_objectives(folder), secret=read_secret(folder), traffic_profiles=profiles, probes=read_probes(folder),
    )


def loaded(path: Path) -> Any:
    if not path.is_file():
        raise CatalogBroken(f"{path} is missing")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def gateway_names(folder: Path) -> set[str]:
    devices = (loaded(folder / "topology.yaml") or {}).get("devices") or {}
    return {name for device in devices.values() if GATEWAY in (device.get("roles") or [])
            for name in device.get("names") or []}


def traffic_profiles(folder: Path) -> tuple[str, ...]:
    if not (folder / "traffic.yaml").is_file():
        return ()
    return tuple(sorted((loaded(folder / "traffic.yaml") or {}).get("profiles") or {}))


def read_objectives(folder: Path) -> tuple[Objective, ...]:
    tiers = (loaded(folder / "objectives.yaml") or {}).get("tiers") or []
    try:
        return tuple(Objective(key=tier["key"], name=tier["name"], category=tier["category"],
                               difficulty=int(tier["difficulty"]),
                               rule={name: value for name, value in tier.items() if name not in TIER_FIELDS})
                     for tier in tiers)
    except (KeyError, TypeError, ValueError) as broken:
        raise CatalogBroken(f"{folder / 'objectives.yaml'} has a malformed tier: {broken!r}") from broken


def read_secret(folder: Path) -> dict[str, Any]:
    secret = (loaded(folder / "objectives.yaml") or {}).get("secret")
    if not isinstance(secret, dict) or not isinstance(secret.get("role"), str):
        raise CatalogBroken(f"{folder / 'objectives.yaml'} has no secret with the role that holds it")
    return dict(secret)


def read_cases(path: Path) -> tuple[Case, ...]:
    if not path.is_file():
        raise CatalogBroken(f"{path} is missing")
    cases = tuple(Case(name=case["name"], malicious=bool(case["malicious"]), tool_case=bool(case.get("tool")),
                       expect=case.get("expect")) for case in load_cases(path))
    names = [case.name for case in cases]
    if len(set(names)) != len(names):
        raise CatalogBroken(f"{path} names a case twice")
    if not any(not case.malicious for case in cases):
        raise CatalogBroken(f"{path} has no benign case")
    return cases


def read_probes(folder: Path) -> Probes | None:
    manifest = folder / "probes" / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        declared = json.loads(manifest.read_text(encoding="utf-8"))
        return Probes(image_digest=declared["image_digest"], recorded_at=declared["recorded_at"],
                      cases=dict(declared.get("cases") or {}))
    except (KeyError, TypeError, ValueError) as broken:
        raise CatalogBroken(f"{manifest} is malformed: {broken!r}") from broken
