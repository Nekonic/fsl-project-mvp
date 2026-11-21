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
INSIDE = ("mgmt",)
OPTIONAL_SECTIONS = ("backups",)
ROLES = ("kali", "waf", "infra", "target")
SLOT_FLAVOR = "dba.small"
SLOT_IMAGE = "cr-{role}-bake1"
POOL = {"board": 3, "corp": 1}
TARGET_TAG = "cf8d735e66c5115ce3d8e06dbdef7967635532ef"
RETIRED = {"network": ("estate", "mtu"), "compute": ("slots",), "flavors": ("range",)}
DOCKER_DEFAULT_POOLS = ("172.17.0.0/16", "172.18.0.0/16", "172.19.0.0/16", "172.20.0.0/14",
                        "172.24.0.0/14", "172.28.0.0/14", "192.168.0.0/16")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
CLOUDS = Path("~/.config/openstack/clouds.yaml")
ENTRY = {
    "keystone": ("auth", "auth_url"), "user": ("auth", "username"), "password": ("auth", "password"),
    "project": ("auth", "project_name"), "user_domain": ("auth", "user_domain_name"),
    "project_domain": ("auth", "project_domain_name"), "region": ("region_name",),
}
PROJECT = "fsl-range"
OPEN_TO_ALL = ["0.0.0.0/0"]
NEEDS = {"platform": {"ram": 8192, "vcpus": 2, "disk": 40}}
SETTING = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<gap> *)(?P<value>[^#]*?)(?P<comment> +#.*)?$")


class Invalid(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    cloud: str
    file: str
    keystone: str
    user: str
    password: str = field(repr=False)
    project: str
    user_domain: str
    project_domain: str
    region: str
    interface: str

    def cli_environment(self) -> dict[str, str]:
        return {"OS_CLOUD": self.cloud, "OS_CLIENT_CONFIG_FILE": self.file}


def entries(path: Path = CLOUDS) -> dict:
    path = Path(path).expanduser()
    if not path.is_file():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise Invalid(f"{path} is not YAML: {error}") from error
    clouds = document.get("clouds") if isinstance(document, dict) else None
    return clouds if isinstance(clouds, dict) else {}


def _setting(entry: dict, path: tuple[str, ...]):
    for key in path:
        entry = entry.get(key) if isinstance(entry, dict) else None
    return entry


def signed_in(name: str, path: Path = CLOUDS) -> Identity:
    path = Path(path).expanduser()
    entry = entries(path).get(name)
    if not isinstance(entry, dict):
        raise Invalid(f"{path} has no entry {name}, so nothing was changed; run bin/cloud init first")
    found = {field_name: _setting(entry, where) for field_name, where in ENTRY.items()}
    missing = [".".join(ENTRY[field_name]) for field_name, value in found.items() if not value]
    if missing:
        raise Invalid(f"{path}: the entry {name} has no {', '.join(missing)}; run bin/cloud init to rewrite it")
    keystone = found.pop("keystone").rstrip("/").removesuffix("/v3")
    complaint = _url(keystone)
    if complaint:
        raise Invalid(f"{path}: clouds.{name}.auth.auth_url {complaint}")
    return Identity(cloud=name, file=str(path), keystone=keystone,
                    interface=_setting(entry, ("interface",)) or "public", **found)


def merged_clouds(text: str | None, name: str, entry: dict) -> str:
    document = (yaml.safe_load(text) if text else None) or {}
    if not isinstance(document, dict) or not isinstance(document.get("clouds") or {}, dict):
        raise Invalid("the clouds.yaml there holds no clouds: mapping, so it was left as it is")
    document["clouds"] = {**(document.get("clouds") or {}), name: entry}
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def write_clouds(path: Path, name: str, entry: dict) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = merged_clouds(path.read_text(encoding="utf-8") if path.is_file() else None, name, entry)
    staged = path.with_name(path.name + ".new")
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as written:
        written.write(text)
    os.replace(staged, path)


def external_network(networks: list[dict], named: str = "") -> str:
    external = [network["name"] for network in networks if network.get("external")]
    if named in external:
        return named
    if len(external) == 1:
        return external[0]
    if external:
        raise Invalid("more than one external network (router:external): " + ", ".join(sorted(external))
                      + "; set network.external in cloud.yaml to one of them and run init again")
    names = ", ".join(sorted(network["name"] for network in networks)) or "none at all"
    raise Invalid(f"no external network (router:external); the networks are: {names}. "
                  "An admin creates one first (docs/OPENSTACK.md §2.5)")


def _fits(flavor: dict, role: str) -> bool:
    return all((flavor.get(measure) or 0) >= least for measure, least in NEEDS[role].items())


def fitting_flavor(flavors: list[dict], role: str, named: str = "") -> dict:
    kept = [flavor for flavor in flavors if flavor["name"] == named and _fits(flavor, role)]
    if kept:
        return kept[0]
    fitting = sorted((flavor for flavor in flavors if _fits(flavor, role)),
                     key=lambda flavor: (flavor["ram"], flavor["vcpus"], flavor["disk"], flavor["name"]))
    if not fitting:
        need = NEEDS[role]
        raise Invalid(f"no flavor fits the {role} VM, which needs RAM {need['ram']} MB, {need['vcpus']} vCPU "
                      f"and a {need['disk']} GB disk or more; an admin creates one (openstack flavor create "
                      f"--ram {need['ram']} --vcpus {need['vcpus']} --disk {need['disk']} <name>), init never does")
    return fitting[0]


def quota_shortfall(limits: dict, platform: dict, roles: dict[str, dict], slots: int) -> list[str]:
    needed = {
        "instances": 1 + slots * len(roles),
        "cores": platform["vcpus"] + slots * sum(flavor["vcpus"] for flavor in roles.values()),
        "ram": platform["ram"] + slots * sum(flavor["ram"] for flavor in roles.values()), "floating_ips": 1,
    }
    return [f"{name}: the quota is {limits.get(name)}, the platform and {slots} slots of {len(roles)} VMs need {need}"
            for name, need in needed.items()
            if limits.get(name) is not None and 0 <= limits[name] < need]


def _scalar(value) -> str:
    return value if isinstance(value, str) and NAME.fullmatch(value) else yaml.safe_dump(
        value, default_flow_style=True, width=1000).removesuffix("\n...\n").strip()


def with_settings(text: str, settings: dict[tuple[str, ...], object]) -> str:
    lines = text.splitlines()
    for path, value in settings.items():
        lines = _set(lines, path, _scalar(value))
    return "\n".join(lines) + "\n"


def _set(lines: list[str], path: tuple[str, ...], value: str) -> list[str]:
    stack: list[tuple[int, str]] = []
    seen = {(): -1}
    for at, line in enumerate(lines):
        found = SETTING.match(line)
        if not found:
            continue
        while stack and stack[-1][0] >= len(found["indent"]):
            stack.pop()
        stack.append((len(found["indent"]), found["key"]))
        here = tuple(key for _, key in stack)
        seen[here] = at
        if here == path:
            start = f"{found['indent']}{found['key']}: {value}"
            comment = found["comment"] or ""
            lines[at] = start.ljust(len(line) - len(comment)) + comment if comment else start
            return lines
    depth = max(depth for depth in range(len(path)) if path[:depth] in seen)
    added = [f"{'  ' * level}{key}:" for level, key in enumerate(path[:-1]) if level >= depth]
    added.append(f"{'  ' * (len(path) - 1)}{path[-1]}: {value}")
    at = seen[path[:depth]]
    if at < 0:
        at = next((n for n, line in enumerate(lines) if SETTING.match(line)), len(lines))
        return lines[:at] + added + [""] + lines[at:]
    return lines[:at + 1] + added + lines[at + 1:]


@dataclass(frozen=True)
class Cloud:
    cloud: str
    external_network: str
    platform_cidr: str
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
    images: dict[str, str] = field(default_factory=dict)
    pool: dict[str, int] = field(default_factory=lambda: dict(POOL))
    target_tag: str = TARGET_TAG
    allowed: tuple[str, ...] = tuple(OPEN_TO_ALL)
    backups_keep: int = 1
    signed_in: Identity | None = None

    def heat_parameters(self, floating_ip_id: str = "") -> dict[str, str]:
        if self.signed_in is None:
            raise Invalid(f"no OpenStack identity: clouds.yaml's entry {self.cloud} was not read")
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
            "subnets": joined(self.inside), "management": self.inside["mgmt"],
            "pool": joined(self.pool), "images": joined(self.images), "target_tag": self.target_tag,
            "flavors": joined({role: name for role, name in self.flavors.items() if role in ROLES}),
            "allowed": ",".join(self.allowed),
        }

    @property
    def slots(self) -> int:
        return sum(self.pool.values())


def joined(pairs: dict) -> str:
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


def _dns(value) -> str | None:
    if not isinstance(value, list) or not value:
        return "must be a list of at least one IPv4 address"
    for entry in value:
        try:
            ipaddress.IPv4Address(str(entry))
        except ValueError:
            return f"holds {entry!r}, which is not an IPv4 address"
    return None


def _allowed(value) -> str | None:
    if not isinstance(value, list) or not value:
        return "must be a list of at least one IPv4 network, such as [0.0.0.0/0]"
    for entry in value:
        try:
            network = ipaddress.ip_network(str(entry), strict=True)
        except ValueError:
            return f"holds {entry!r}, which is not an IPv4 network such as 203.0.113.0/24"
        if network.version != 4:
            return f"holds {entry!r}, which is not an IPv4 network"
    return None


def _address(value) -> str | None:
    try:
        ipaddress.IPv4Address(str(value))
    except ValueError:
        return "must be the IPv4 address of a floating IP this project already holds"
    return None


def _named_per(value, keys: tuple[str, ...], what: str, required: tuple[str, ...] = ()) -> str | None:
    if not isinstance(value, dict):
        return f"must map {', '.join(keys)} to {what} names"
    missing = [key for key in required if key not in value]
    if missing:
        return f"lacks {', '.join(missing)}"
    extra = [key for key in value if key not in keys and key not in RETIRED["flavors"]]
    if extra:
        return f"names {', '.join(map(str, extra))}, which is none of {', '.join(keys)}"
    wrong = [key for key, name in value.items() if key in keys and _name(name)]
    return f"has {', '.join(map(str, wrong))} not naming a {what}" if wrong else None


def _flavors(value) -> str | None:
    return _named_per(value, ("platform", *ROLES), "flavor", ("platform",))


def _images(value) -> str | None:
    return _named_per(value, ROLES, "image")


def _tag(value) -> str | None:
    return None if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) else (
        "must be the full commit the target image's wargame images were pulled at (CR_IMAGE_TAG of its bake)")


def _pool(value) -> str | None:
    if not isinstance(value, dict) or not value:
        return "must map each wargame to its number of ready slots, such as {board: 3, corp: 1}"
    wrong = [str(key) for key, count in value.items()
             if _name(str(key)) or isinstance(count, bool) or not isinstance(count, int) or count < 0]
    if wrong:
        return f"has {', '.join(wrong)} not mapped to a whole number of slots, 0 or more"
    return None if sum(value.values()) else "holds no slot"


def _keep(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "must be a whole number of backups, 1 or more: the one just taken is always kept"
    return None


SCHEMA = {
    "network": {
        "external": (_name, True), "address": (_address, False), "dns": (_dns, True),
        "platform": (_cidr, True), "mgmt": (_cidr, True), "allowed": (_allowed, False),
    },
    "compute": {
        "base_image": (_name, True), "availability_zone": (_optional_name, False),
        "flavors": (_flavors, True), "images": (_images, False), "pool": (_pool, False),
        "target_tag": (_tag, False),
    },
    "keys": {"key_name": (_name, True), "key_file": (_text, True), "range": (_text, True)},
    "platform": {"stack": (_name, True), "repository": (_url, True), "ref": (_name, True)},
    "backups": {"keep": (_keep, False)},
}
SETTINGS = ("cloud",)


def _complaints(document) -> list[str]:
    if not isinstance(document, dict):
        return ["the file holds no mapping of sections"]
    said = [f"{section}: not a section this file has (expected one of {', '.join(SCHEMA)})"
            for section in document if section not in SCHEMA and section not in SETTINGS]
    if document.get("cloud") in ("", None):
        said.append("cloud: missing, the clouds.yaml entry to sign in with; bin/cloud init writes it")
    elif _name(document["cloud"]):
        said.append(f"cloud: {_name(document['cloud'])}")
    for section, keys in SCHEMA.items():
        entries = document.get(section)
        if entries is None and section in OPTIONAL_SECTIONS:
            continue
        if not isinstance(entries, dict):
            said.append(f"{section}: missing, or not a mapping")
            continue
        said += [f"{section}.{key}: not a setting this section has (expected one of {', '.join(keys)})"
                 for key in entries if key not in keys and key not in RETIRED.get(section, ())]
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
    flavors = {str(role): name for role, name in compute["flavors"].items() if role not in RETIRED["flavors"]}
    return Cloud(
        cloud=document["cloud"],
        external_network=network["external"], address=str(network.get("address") or ""),
        dns=tuple(map(str, network["dns"])), platform_cidr=network["platform"],
        inside={segment: network[segment] for segment in INSIDE},
        base_image=compute["base_image"],
        availability_zone=compute.get("availability_zone") or "",
        flavors={**{role: SLOT_FLAVOR for role in ROLES}, **flavors},
        images={**{role: SLOT_IMAGE.format(role=role) for role in ROLES}, **(compute.get("images") or {})},
        pool={str(wargame): count for wargame, count in (compute.get("pool") or POOL).items()},
        target_tag=compute.get("target_tag") or TARGET_TAG,
        allowed=tuple(map(str, network.get("allowed") or OPEN_TO_ALL)),
        key_name=keys["key_name"], key_file=keys["key_file"],
        range_key=keys["range"],
        stack=platform["stack"], repository=platform["repository"], ref=platform["ref"],
        backups_keep=backups.get("keep") or 1,
    )


def read(path: Path = CONFIGURED) -> Cloud:
    path = Path(path)
    if not path.is_file():
        raise Invalid(f"{path} does not exist; bin/cloud init writes it")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise Invalid(f"{path} is not YAML: {error}") from error
    return parse(document, str(path))
