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
OPNSENSE_FAMILY = "fsl-opnsense-"
INSIDE = ("estate", "mgmt")
FIXED_FLAVORS = ("platform", "builder", "range")
REQUIRED_FLAVORS = (*FIXED_FLAVORS, "edge")
DOCKER_DEFAULT_POOLS = ("172.17.0.0/16", "172.18.0.0/16", "172.19.0.0/16", "172.20.0.0/14",
                        "172.24.0.0/14", "172.28.0.0/14", "192.168.0.0/16")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"\d+\.\d+(\.\d+)?")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
ENVIRONMENT = re.compile(r"[A-Z_][A-Z0-9_]*")


class Invalid(ValueError):
    pass


@dataclass(frozen=True)
class OPNsense:
    version: str
    mirror: str
    image_sha256: str
    pubkey_sha256: str

    @property
    def image(self) -> str:
        return f"{OPNSENSE_FAMILY}{self.version}"

    @property
    def nano(self) -> str:
        return f"OPNsense-{self.version}-nano-amd64.img"

    def pairs(self) -> dict[str, str]:
        return {"version": self.version, "mirror": self.mirror,
                "image_sha256": self.image_sha256, "pubkey_sha256": self.pubkey_sha256}


@dataclass(frozen=True)
class Cloud:
    keystone: str
    region: str
    interface: str
    domain: str
    project: str
    user: str
    external_network: str
    platform_cidr: str
    mtu: int
    base_image: str
    operator_key: str
    operator_key_file: str
    range_key: str
    opnsense: OPNsense
    stack: str
    repository: str
    ref: str
    password_file: str = ""
    password_env: str = ""
    availability_zone: str = ""
    address: str = ""
    dns: tuple[str, ...] = ()
    inside: dict[str, str] = field(default_factory=dict)
    flavors: dict[str, str] = field(default_factory=dict)
    slots: int = 1

    @property
    def role_flavors(self) -> dict[str, str]:
        return {role: name for role, name in self.flavors.items() if role not in FIXED_FLAVORS}

    def password(self, environ=os.environ) -> str:
        if self.password_env:
            found = environ.get(self.password_env, "")
            if not found:
                raise Invalid(f"identity.password_env names {self.password_env}, which is unset")
            return found
        path = Path(self.password_file).expanduser()
        if not path.is_file():
            raise Invalid(f"identity.password_file names {path}, which does not exist")
        return path.read_text().strip()

    def heat_parameters(self, floating_ip_id: str = "") -> dict[str, str]:
        return {
            "keystone": self.keystone, "user": self.user, "domain": self.domain,
            "region": self.region, "interface": self.interface,
            "image": self.base_image, "flavor": self.flavors["platform"],
            "key_name": self.operator_key, "external_network": self.external_network,
            "floating_address": self.address, "floating_ip_id": floating_ip_id,
            "availability_zone": self.availability_zone,
            "cidr": self.platform_cidr, "dns": ",".join(self.dns),
            "repository": self.repository, "ref": self.ref,
            "range_flavor": self.flavors["range"], "build_flavor": self.flavors["builder"],
            "role_flavors": joined(self.role_flavors), "subnets": joined(self.inside),
            "range_mtu": str(self.mtu), "opnsense": joined(self.opnsense.pairs()),
            "slots": str(self.slots),
        }

    def cli_environment(self, environ=os.environ) -> dict[str, str]:
        return {
            "OS_AUTH_URL": f"{self.keystone}/v3", "OS_IDENTITY_API_VERSION": "3",
            "OS_USERNAME": self.user, "OS_PASSWORD": self.password(environ),
            "OS_PROJECT_NAME": self.project, "OS_USER_DOMAIN_ID": self.domain,
            "OS_PROJECT_DOMAIN_ID": self.domain, "OS_REGION_NAME": self.region,
            "OS_INTERFACE": self.interface,
        }


def joined(pairs: dict[str, str]) -> str:
    return " ".join(f"{key}={value}" for key, value in pairs.items())


def pairs(text: str) -> dict[str, str]:
    found = {}
    for word in (text or "").split():
        key, equals, value = word.partition("=")
        if not equals or not key or not value:
            raise Invalid(f"{word!r} is not key=value")
        found[key] = value
    return found


def opnsense_from(text: str) -> OPNsense | None:
    given = pairs(text)
    if not given:
        return None
    wanted = ("version", "mirror", "image_sha256", "pubkey_sha256")
    missing = [key for key in wanted if key not in given]
    if missing:
        raise Invalid(f"the OPNsense settings lack {', '.join(missing)}")
    return OPNsense(**{key: given[key] for key in wanted})


def _url(value) -> str | None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return "must be an http:// or https:// URL"
    return None


def _keystone(value) -> str | None:
    said = _url(value)
    if said:
        return said
    if value.rstrip("/").endswith("/v3"):
        return "is Keystone's base URL without /v3"
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


def _sha256(value) -> str | None:
    return None if isinstance(value, str) and SHA256.fullmatch(value) else "must be 64 lower-case hex digits"


def _version(value) -> str | None:
    return None if isinstance(value, str) and VERSION.fullmatch(value) else "must be a release such as \"26.7\" (quoted)"


def _flavors(value) -> str | None:
    if not isinstance(value, dict):
        return "must map platform, builder, range, edge and optional role names to flavor names"
    missing = [key for key in REQUIRED_FLAVORS if key not in value]
    if missing:
        return f"lacks {', '.join(missing)}"
    wrong = [key for key, name in value.items() if _name(name) or _name(str(key))]
    return f"has {', '.join(map(str, wrong))} not naming a flavor" if wrong else None


def _slots(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "must be a whole number of range slots, 1 or more"
    return None


def _environment(value) -> str | None:
    return None if isinstance(value, str) and ENVIRONMENT.fullmatch(value) else "must be an environment variable name"


SCHEMA = {
    "identity": {
        "keystone": (_keystone, True), "region": (_name, True), "interface": (_name, True),
        "domain": (_name, True), "project": (_name, True), "user": (_name, True),
        "password_file": (_text, False), "password_env": (_environment, False),
    },
    "network": {
        "external": (_name, True), "address": (_address, False), "dns": (_dns, True), "mtu": (_mtu, True),
        "platform": (_cidr, True), "estate": (_cidr, True), "mgmt": (_cidr, True),
    },
    "compute": {
        "base_image": (_name, True), "availability_zone": (_optional_name, False),
        "flavors": (_flavors, True), "slots": (_slots, False),
    },
    "keys": {"operator": (_name, True), "operator_file": (_text, True), "range": (_text, True)},
    "opnsense": {
        "version": (_version, True), "mirror": (_url, True),
        "image_sha256": (_sha256, True), "pubkey_sha256": (_sha256, True),
    },
    "platform": {"stack": (_name, True), "repository": (_url, True), "ref": (_name, True)},
}


def _complaints(document) -> list[str]:
    if not isinstance(document, dict):
        return ["the file holds no mapping of sections"]
    said = [f"{section}: not a section this file has (expected one of {', '.join(SCHEMA)})"
            for section in document if section not in SCHEMA]
    for section, keys in SCHEMA.items():
        entries = document.get(section)
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
    identity = document.get("identity") if isinstance(document.get("identity"), dict) else {}
    if bool(identity.get("password_file")) == bool(identity.get("password_env")):
        said.append("identity: give exactly one of password_file and password_env; "
                    "the password itself never goes in this file")
    return said + _overlaps(document.get("network"))


def _compose_networks(path: Path = COMPOSE) -> dict[str, ipaddress.IPv4Network]:
    if not path.is_file():
        return {}
    networks = (yaml.safe_load(path.read_text()) or {}).get("networks") or {}
    return {
        f"the compose network {name}": ipaddress.ip_network(pool["subnet"])
        for name, entry in networks.items()
        for pool in ((entry or {}).get("ipam") or {}).get("config") or []
        if pool.get("subnet")
    }


def _origins(path: Path = DECLARATION) -> dict[str, ipaddress.IPv4Network]:
    if not path.is_file():
        return {}
    declared = yaml.safe_load(path.read_text()) or {}
    return {
        f"origin {origin['id']}": ipaddress.ip_network(origin["subnet"])
        for segment in declared.get("segments") or []
        for origin in segment.get("origins") or []
    }


def taken() -> dict[str, ipaddress.IPv4Network]:
    return {
        **{f"docker's default address pool {pool}": ipaddress.ip_network(pool)
           for pool in DOCKER_DEFAULT_POOLS},
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
    identity, network, compute = document["identity"], document["network"], document["compute"]
    keys, platform = document["keys"], document["platform"]
    return Cloud(
        keystone=identity["keystone"].rstrip("/"), region=identity["region"],
        interface=identity["interface"], domain=identity["domain"],
        project=identity["project"], user=identity["user"],
        password_file=identity.get("password_file") or "",
        password_env=identity.get("password_env") or "",
        external_network=network["external"], address=str(network.get("address") or ""),
        dns=tuple(map(str, network["dns"])),
        mtu=network["mtu"], platform_cidr=network["platform"],
        inside={segment: network[segment] for segment in INSIDE},
        base_image=compute["base_image"],
        availability_zone=compute.get("availability_zone") or "",
        flavors={str(role): name for role, name in compute["flavors"].items()},
        slots=compute.get("slots") or 1,
        operator_key=keys["operator"], operator_key_file=keys["operator_file"],
        range_key=keys["range"],
        opnsense=OPNsense(**document["opnsense"]),
        stack=platform["stack"], repository=platform["repository"], ref=platform["ref"],
    )


def read(path: Path = CONFIGURED) -> Cloud:
    path = Path(path)
    if not path.is_file():
        raise Invalid(
            f"{path} does not exist; copy {EXAMPLE.name} beside it to {path.name} "
            f"and fill in this cloud's values"
        )
    try:
        document = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise Invalid(f"{path} is not YAML: {error}") from error
    return parse(document, str(path))
