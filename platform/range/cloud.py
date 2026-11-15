from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "deploy/openstack"
EXAMPLE = FOLDER / "cloud.example.yaml"
CONFIGURED = FOLDER / "cloud.yaml"
COMPOSE = ROOT / "compose.yaml"
DECLARATION = Path(__file__).resolve().parent / "declaration.yaml"
INSIDE = ("estate", "mgmt")
OPTIONAL_SECTIONS = ("backups",)
REQUIRED_FLAVORS = ("platform", "range")
RANGE_HOST_POOL = "10.40.0.0/16"
DOCKER_DEFAULT_POOLS = ("172.17.0.0/16", "172.18.0.0/16", "172.19.0.0/16", "172.20.0.0/14",
                        "172.24.0.0/14", "172.28.0.0/14", "192.168.0.0/16")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
RC = {
    "keystone": "OS_AUTH_URL", "user": "OS_USERNAME", "password": "OS_PASSWORD",
    "project": "OS_PROJECT_NAME", "user_domain": "OS_USER_DOMAIN_NAME",
    "project_domain": "OS_PROJECT_DOMAIN_NAME", "region": "OS_REGION_NAME", "interface": "OS_INTERFACE",
}


class Invalid(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    keystone: str
    user: str
    password: str = field(repr=False)
    project: str
    user_domain: str
    project_domain: str
    region: str
    interface: str

    def cli_environment(self) -> dict[str, str]:
        return {
            "OS_AUTH_URL": self.keystone, "OS_IDENTITY_API_VERSION": "3",
            "OS_USERNAME": self.user, "OS_PASSWORD": self.password,
            "OS_PROJECT_NAME": self.project, "OS_USER_DOMAIN_NAME": self.user_domain,
            "OS_PROJECT_DOMAIN_NAME": self.project_domain, "OS_REGION_NAME": self.region,
            "OS_INTERFACE": self.interface,
        }


def identity(environ=os.environ) -> Identity:
    missing = [variable for variable in RC.values() if not environ.get(variable, "").strip()]
    if missing:
        raise Invalid(
            f"the environment has no {', '.join(missing)}; source the project user's RC file "
            f"(README, install step 6) before bin/cloud or bin/platform-rebuild"
        )
    keystone = environ["OS_AUTH_URL"].strip().rstrip("/").removesuffix("/v3")
    complaint = _url(keystone)
    if complaint:
        raise Invalid(f"OS_AUTH_URL {complaint}")
    return Identity(keystone=keystone, **{
        name: environ[variable].strip() for name, variable in RC.items() if name != "keystone"
    })


@dataclass(frozen=True)
class Cloud:
    external_network: str
    platform_cidr: str
    mtu: int
    base_image: str
    key_name: str
    key_file: str
    range_key: str
    stack: str
    repository: str
    ref: str
    availability_zone: str = ""
    address: str = ""
    dns: tuple[str, ...] = ()
    inside: dict[str, str] = field(default_factory=dict)
    flavors: dict[str, str] = field(default_factory=dict)
    slots: int = 1
    backups_keep: int = 1
    signed_in: Identity | None = None

    def heat_parameters(self, floating_ip_id: str = "") -> dict[str, str]:
        if self.signed_in is None:
            raise Invalid("no OpenStack identity: source the project user's RC file first")
        signed_in = self.signed_in
        return {
            "keystone": signed_in.keystone, "user": signed_in.user, "domain": signed_in.user_domain,
            "region": signed_in.region, "interface": signed_in.interface,
            "image": self.base_image, "flavor": self.flavors["platform"],
            "key_name": self.key_name, "external_network": self.external_network,
            "floating_address": self.address, "floating_ip_id": floating_ip_id,
            "availability_zone": self.availability_zone,
            "cidr": self.platform_cidr, "dns": ",".join(self.dns),
            "repository": self.repository, "ref": self.ref,
            "range_flavor": self.flavors["range"], "subnets": joined(self.inside),
            "management": self.inside["mgmt"],
            "range_mtu": str(self.mtu), "slots": str(self.slots),
        }


def joined(pairs: dict[str, str]) -> str:
    return " ".join(f"{key}={value}" for key, value in pairs.items())


def _url(value) -> str | None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return "must be an http:// or https:// URL"
    return None


def _name(value) -> str | None:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        return "must be a name of letters, digits, '.', '_', ':' or '-'"
    return None


def _text(value) -> str | None:
    return None if isinstance(value, str) and value.strip() else "must be a non-empty string"


def _optional_name(value) -> str | None:
    return None if value in ("", None) else _name(value)


def _cidr(value) -> str | None:
    try:
        network = ipaddress.ip_network(str(value), strict=True)
    except ValueError:
        return "must be an IPv4 network such as 10.30.0.0/24"
    if network.version != 4 or not network.is_private:
        return "must be a private IPv4 network"
    return None


def _estate(value) -> str | None:
    said = _cidr(value)
    if said:
        return said
    if ipaddress.ip_network(str(value)).prefixlen > 16:
        return "must be a /16 or wider: slot N's estate is its Nth /24, such as 10.30.0.0/16"
    return None


def _mtu(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1280 <= value <= 9000:
        return "must be a whole number between 1280 and 9000"
    return None


def _dns(value) -> str | None:
    if not isinstance(value, list) or not value:
        return "must be a list of at least one IPv4 address"
    for entry in value:
        try:
            ipaddress.IPv4Address(str(entry))
        except ValueError:
            return f"holds {entry!r}, which is not an IPv4 address"
    return None


def _address(value) -> str | None:
    try:
        ipaddress.IPv4Address(str(value))
    except ValueError:
        return "must be the IPv4 address of a floating IP this project already holds"
    return None


def _flavors(value) -> str | None:
    if not isinstance(value, dict):
        return "must map platform and range to flavor names"
    missing = [key for key in REQUIRED_FLAVORS if key not in value]
    if missing:
        return f"lacks {', '.join(missing)}"
    extra = [key for key in value if key not in REQUIRED_FLAVORS]
    if extra:
        return f"names {', '.join(map(str, extra))}, which the range no longer has: one range host runs every slot"
    wrong = [key for key, name in value.items() if _name(name) or _name(str(key))]
    return f"has {', '.join(map(str, wrong))} not naming a flavor" if wrong else None


def _slots(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "must be a whole number of range slots, 1 or more"
    return None


def _keep(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "must be a whole number of backups, 1 or more: the one just taken is always kept"
    return None


SCHEMA = {
    "network": {
        "external": (_name, True), "address": (_address, False), "dns": (_dns, True), "mtu": (_mtu, True),
        "platform": (_cidr, True), "estate": (_estate, True), "mgmt": (_cidr, True),
    },
    "compute": {
        "base_image": (_name, True), "availability_zone": (_optional_name, False),
        "flavors": (_flavors, True), "slots": (_slots, False),
    },
    "keys": {"key_name": (_name, True), "key_file": (_text, True), "range": (_text, True)},
    "platform": {"stack": (_name, True), "repository": (_url, True), "ref": (_name, True)},
    "backups": {"keep": (_keep, False)},
}


def _complaints(document) -> list[str]:
    if not isinstance(document, dict):
        return ["the file holds no mapping of sections"]
    said = [f"{section}: not a section this file has (expected one of {', '.join(SCHEMA)})"
            for section in document if section not in SCHEMA]
    for section, keys in SCHEMA.items():
        entries = document.get(section)
        if entries is None and section in OPTIONAL_SECTIONS:
            continue
        if not isinstance(entries, dict):
            said.append(f"{section}: missing, or not a mapping")
            continue
        said += [f"{section}.{key}: not a setting this section has (expected one of {', '.join(keys)})"
                 for key in entries if key not in keys]
        for key, (check, required) in keys.items():
            if key not in entries or entries[key] in ("", None):
                if required:
                    said.append(f"{section}.{key}: missing")
                continue
            complaint = check(entries[key])
            if complaint:
                said.append(f"{section}.{key}: {complaint}")
    return said + _overlaps(document.get("network"))


def _compose_networks(path: Path = COMPOSE) -> dict[str, ipaddress.IPv4Network]:
    if not path.is_file():
        return {}
    networks = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("networks") or {}
    return {
        f"the compose network {name}": ipaddress.ip_network(pool["subnet"])
        for name, entry in networks.items()
        for pool in ((entry or {}).get("ipam") or {}).get("config") or []
        if pool.get("subnet")
    }


def _origins(path: Path = DECLARATION) -> dict[str, ipaddress.IPv4Network]:
    if not path.is_file():
        return {}
    declared = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        f"origin {origin['id']}": ipaddress.ip_network(origin["subnet"])
        for segment in declared.get("segments") or []
        for origin in segment.get("origins") or []
    }


def taken() -> dict[str, ipaddress.IPv4Network]:
    return {
        **{f"docker's default address pool {pool}": ipaddress.ip_network(pool)
           for pool in DOCKER_DEFAULT_POOLS},
        f"the range host's docker address pool {RANGE_HOST_POOL}": ipaddress.ip_network(RANGE_HOST_POOL),
        **_compose_networks(),
        **_origins(),
    }


def _overlaps(network) -> list[str]:
    if not isinstance(network, dict):
        return []
    named = {key: network.get(key) for key in ("platform", *INSIDE)}
    if any(_cidr(value) for value in named.values()):
        return []
    held = {key: ipaddress.ip_network(value) for key, value in named.items()}
    names = list(held)
    among = [
        f"network: {one} {held[one]} overlaps {other} {held[other]}"
        for at, one in enumerate(names) for other in names[at + 1:]
        if held[one].overlaps(held[other])
    ]
    return among + [
        f"network: {key} {held[key]} overlaps {name} {used}"
        for key in names for name, used in taken().items()
        if held[key].overlaps(used)
    ]


def parse(document, source: str = "cloud.yaml") -> Cloud:
    said = _complaints(document)
    if said:
        raise Invalid(f"{source} is not usable:\n  " + "\n  ".join(said))
    network, compute = document["network"], document["compute"]
    keys, platform = document["keys"], document["platform"]
    backups = document.get("backups") or {}
    return Cloud(
        external_network=network["external"], address=str(network.get("address") or ""),
        dns=tuple(map(str, network["dns"])),
        mtu=network["mtu"], platform_cidr=network["platform"],
        inside={segment: network[segment] for segment in INSIDE},
        base_image=compute["base_image"],
        availability_zone=compute.get("availability_zone") or "",
        flavors={str(role): name for role, name in compute["flavors"].items()},
        slots=compute.get("slots") or 1,
        key_name=keys["key_name"], key_file=keys["key_file"],
        range_key=keys["range"],
        stack=platform["stack"], repository=platform["repository"], ref=platform["ref"],
        backups_keep=backups.get("keep") or 1,
    )


def read(path: Path = CONFIGURED) -> Cloud:
    path = Path(path)
    if not path.is_file():
        raise Invalid(
            f"{path} does not exist; copy {EXAMPLE.name} beside it to {path.name} "
            f"and fill in this cloud's values"
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise Invalid(f"{path} is not YAML: {error}") from error
    return parse(document, str(path))
