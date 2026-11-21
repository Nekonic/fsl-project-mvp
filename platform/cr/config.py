from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.conf import settings

SOURCE = Path(__file__).resolve().parents[2]
TOPOLOGIES = "wargames/*/topology.yaml"
DECLARATION = "platform/sandbox/declaration.yaml"
SURICATA_RULES = "/var/lib/suricata/rules/local.rules"
SURICATA_IMAGE = "jasonish/suricata@sha256:7ca2546f7f2735f621b981b6a5ec84fb962984636f7629a1a2fa6a324d4b6840"
CRS_EXCLUSIONS = "/etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
NGINX_RELOAD = "nginx -t 2>&1 && nginx -s reload 2>&1"
NGINX_PID = "/tmp/nginx.pid"
SUBSTRATE = "sandbox.openstack.connect"
ORIGIN = re.compile(r"https?://(?:[a-z0-9.-]+|\[[0-9a-f:.]+\])(?::[0-9]{1,5})?")


@dataclass(frozen=True)
class ElasticConfig:
    url: str = "http://elasticsearch:9200"
    index: str = "logs-*"
    slot_index: str = "logs-{slot}-*"
    pipeline_file: str = str(SOURCE / "deploy/elastic/ingest-pipeline.json")
    pipeline: str = "geoip"

    def index_of(self, slot: int) -> str:
        return self.slot_index.format(slot=slot) if self.slot_index else self.index


@dataclass(frozen=True)
class SensorConfig:
    name: str
    role: str = "sensor"
    rules: str = SURICATA_RULES
    reload: tuple[str, ...] = ()
    image: str = SURICATA_IMAGE
    settings_file: str = "/etc/suricata/suricata.yaml"
    live_logs: str = "/var/log/suricata"
    scratch: str = "/var/lib/cr-ruletest"
    interface: str = "br0"


@dataclass(frozen=True)
class WafConfig:
    role: str = "gateway"
    rules: str = CRS_EXCLUSIONS
    reload: str = NGINX_RELOAD
    pid: str = NGINX_PID
    crs_tree: str = ""
    scratch: str = "/var/lib/cr-crstest"
    probe_template: str = "/usr/local/share/cr/probe.conf"
    probe_upstream: str = "/usr/local/share/cr/probe-upstream.py"
    first_port: int = 18000

    @property
    def tree(self) -> str:
        if self.crs_tree:
            return self.crs_tree
        parts = Path(self.rules).parts
        return str(Path(*parts[:parts.index("rules") - 1])) if "rules" in parts[:-1] else str(Path(self.rules).parent)


@dataclass(frozen=True)
class EdgeConfig:
    role: str = "edge"
    family: str = "ip"
    table: str = "edge"
    pool: str = "pool"
    spent: str = "spent"


@dataclass(frozen=True)
class BoxConfig:
    attacker: str = "cr-kali"
    proxy: str = "cr-kali"
    way_in: str = "cr-edge"
    target_url: str = "http://board.com"
    default_origin: str = ""
    tool_image: str = "cr-kali"
    label_file: str = "/var/lib/session/active"
    command_log: str = "/var/log/commands.log"


@dataclass(frozen=True)
class JumpConfig:
    directory: str = str(SOURCE / "platform/jump")
    port: int = 2222
    host: str = ""


@dataclass(frozen=True)
class KibanaConfig:
    url: str = ""
    objects: str = str(SOURCE / "deploy/kibana/objects.ndjson")

    @property
    def base(self) -> str:
        return self.url or "http://kibana:5601/kibana"


@dataclass(frozen=True)
class GroundTruthConfig:
    board_url: str = "http://board:8000"


@dataclass(frozen=True)
class OpenStackConfig:
    keystone: str = ""
    user: str = ""
    password: str = field(default="", repr=False)
    project: str = ""
    ssh_user: str = ""
    ssh_key: str = ""
    region: str = ""
    interface: str = ""
    domain: str = ""
    source: str = str(SOURCE)
    flavor: str = "dba.small"
    availability_zone: str = ""
    subnets: str = ""
    platform: str = ""
    pool: str = ""
    target_tag: str = ""
    images: str = ""
    flavors: str = ""


@dataclass(frozen=True)
class RefillConfig:
    directory: str = str(SOURCE / "platform/refill")
    wait: float = 1800.0


@dataclass(frozen=True)
class RangeConfig:
    substrate: str = SUBSTRATE
    source: str = str(SOURCE)
    declaration: str = str(SOURCE / DECLARATION)
    openstack: OpenStackConfig = OpenStackConfig()


@dataclass(frozen=True)
class Config:
    range: RangeConfig = RangeConfig()
    elastic: ElasticConfig = ElasticConfig()
    sensors: tuple[SensorConfig, ...] = ()
    waf: WafConfig = WafConfig()
    edge: EdgeConfig = EdgeConfig()
    box: BoxConfig = BoxConfig()
    jump: JumpConfig = JumpConfig()
    kibana: KibanaConfig = KibanaConfig()
    ground_truth: GroundTruthConfig = GroundTruthConfig()
    refill: RefillConfig = RefillConfig()


OPENSTACK_VARIABLES = {
    "keystone": "CR_OPENSTACK_KEYSTONE",
    "user": "CR_OPENSTACK_USER",
    "domain": "CR_OPENSTACK_DOMAIN",
    "project": "CR_OPENSTACK_PROJECT",
    "ssh_user": "CR_OPENSTACK_SSH_USER",
    "ssh_key": "CR_OPENSTACK_SSH_KEY",
    "region": "CR_OPENSTACK_REGION",
    "interface": "CR_OPENSTACK_INTERFACE",
    "availability_zone": "CR_OPENSTACK_AVAILABILITY_ZONE",
    "subnets": "CR_OPENSTACK_SUBNETS",
    "platform": "CR_OPENSTACK_PLATFORM",
    "pool": "CR_OPENSTACK_POOL",
    "target_tag": "CR_OPENSTACK_TARGET_TAG",
    "images": "CR_OPENSTACK_IMAGES",
    "flavors": "CR_OPENSTACK_FLAVORS",
}


def devices(source: Path) -> tuple[dict[str, dict], dict[str, str]]:
    found: dict[str, dict] = {}
    watches: dict[str, str] = {}
    for path in sorted(Path(source).glob(TOPOLOGIES)):
        document = yaml.safe_load(path.read_text()) or {}
        for name, entry in (document.get("devices") or {}).items():
            found.setdefault(name, dict(entry or {}))
        watches.update(document.get("watches") or {})
    return found, watches


def filling(found: Mapping[str, dict], role: str) -> tuple[str, dict]:
    return next(((name, entry) for name, entry in sorted(found.items()) if role in (entry.get("roles") or ())),
                ("", {}))


def sensors(found: Mapping[str, dict], watches: Mapping[str, str]) -> tuple[SensorConfig, ...]:
    listed = []
    for role in sorted(watches):
        name, entry = filling(found, role)
        if not name:
            continue
        listed.append(SensorConfig(name=name, role=role, rules=entry.get("rules") or SURICATA_RULES,
                                   reload=tuple(str(entry.get("reload") or "").split())))
    return tuple(listed)


def waf(found: Mapping[str, dict]) -> WafConfig:
    _, entry = filling(found, "gateway")
    return WafConfig(rules=entry.get("rules") or CRS_EXCLUSIONS, reload=entry.get("reload") or NGINX_RELOAD,
                     pid=entry.get("pid") or NGINX_PID)


def kept_secret(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build(environ: Mapping[str, str] = os.environ, source: Path | str | None = None) -> Config:
    root = Path(source or environ.get("CR_SOURCE") or SOURCE)
    found, watches = devices(root)
    declaration = root / DECLARATION
    declared = yaml.safe_load(declaration.read_text()) if declaration.is_file() else {}
    target_url = environ.get("ATTACKER_TARGET_URL") or environ.get("PUBLIC_TARGET_URL") or BoxConfig.target_url
    attacker, _ = filling(found, "attacker")
    proxy, _ = filling(found, "proxy")
    way_in = filling(found, "edge")[0] or filling(found, "gateway")[0]
    password = kept_secret(environ.get("CR_OPENSTACK_PASSWORD_FILE") or "/run/secrets/openstack_password")
    openstack = OpenStackConfig(source=str(root), password=password,
                                **{name: environ.get(variable, "") for name, variable in OPENSTACK_VARIABLES.items()})
    return Config(
        range=RangeConfig(substrate=environ.get("CR_SUBSTRATE") or SUBSTRATE, source=str(root),
                          declaration=str(declaration), openstack=openstack),
        elastic=ElasticConfig(url=environ.get("ELASTIC_URL") or ElasticConfig.url,
                              index=environ.get("ELASTIC_INDEX") or ElasticConfig.index,
                              slot_index=environ.get("ELASTIC_SESSION_INDEX", ElasticConfig.slot_index),
                              pipeline_file=str(root / "deploy/elastic/ingest-pipeline.json")),
        sensors=sensors(found, watches),
        waf=waf(found),
        box=BoxConfig(attacker=attacker or BoxConfig.attacker, proxy=proxy or attacker or BoxConfig.proxy,
                      way_in=way_in or BoxConfig.way_in, target_url=target_url,
                      default_origin=str((declared or {}).get("default_origin") or ""),
                      tool_image=environ.get("CR_TOOL_IMAGE") or attacker or BoxConfig.tool_image),
        jump=JumpConfig(directory=environ.get("CR_JUMP_DIR") or JumpConfig.directory,
                        port=int(environ.get("CR_JUMP_PORT") or JumpConfig.port),
                        host=environ.get("CR_JUMP_HOST", "")),
        kibana=KibanaConfig(url=environ.get("KIBANA_URL", ""), objects=str(root / "deploy/kibana/objects.ndjson")),
        ground_truth=GroundTruthConfig(board_url=environ.get("BOARD_API_URL") or GroundTruthConfig.board_url),
        refill=RefillConfig(directory=environ.get("CR_REFILL_DIR") or RefillConfig.directory),
    )


@dataclass(frozen=True)
class OriginsConfig:
    console: str = ""
    site: str = ""
    console_port: int = 8000
    site_port: int = 8002

    def console_for(self, host: str) -> str:
        return self.console or f"http://{host}:{self.console_port}"

    def site_for(self, host: str) -> str:
        return self.site or f"http://{host}:{self.site_port}"


def configured() -> Config:
    return build(source=Path(settings.CR_SOURCE))


def origin_of(given: str, variable: str) -> str:
    origin = given.strip().rstrip("/").lower()
    if origin and not ORIGIN.fullmatch(origin):
        raise ValueError(f"{variable} must be a scheme, a host and an optional port, as in https://cr.example, not {given!r}")
    return origin


def origins(environ: Mapping[str, str] = os.environ) -> OriginsConfig:
    return OriginsConfig(console=origin_of(environ.get("CR_CONSOLE_ORIGIN", ""), "CR_CONSOLE_ORIGIN"),
                         site=origin_of(environ.get("CR_SITE_ORIGIN", ""), "CR_SITE_ORIGIN"))


def nginx_origins(given: OriginsConfig) -> str:
    return (f'map $host $console_origin {{ default "{given.console_for("$host")}"; }}\n'
            f'map $host $site_origin {{ default "{given.site_for("$host")}"; }}\n')


if __name__ == "__main__":
    print(nginx_origins(origins()), end="")
