from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import json
import re
import shlex
import tarfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from range.ports import RangeUnavailable

ROLE = "wargames"
TEMPLATE = "deploy/range-host/slot.yaml"
SETUP = "deploy/range-host/setup.sh"
SLOT_SCRIPT = "deploy/range-host/slot.sh"
EDGE_SENSOR = "deploy/range-host/edge-sensor.yaml"
ESTATE_SENSOR = "deploy/range-host/estate-sensor.yaml"
BASELINE_RULES = "deploy/suricata/rules/local.rules"
COMPOSE = "wargames/{wargame}/compose.yaml"
INSTALLED = "/opt/cr"
SCRIPT = f"{INSTALLED}/slot.sh"
READY = "/var/lib/cr/ready"
FAILED = "/var/lib/cr/failed"
SLOT_FILES = f"{INSTALLED}/s{{slot}}"
TAG = re.compile(r"\$\{CR_IMAGE_TAG(?::-[^}]*)?\}")
DROPPED = ("build", "networks", "platform")
FRONT = "estate"
BACKEND = "{wargame}-default"
INTERNET = "internet"
UP_TIMEOUT = 900.0
RESET_TIMEOUT = 600.0
USER_DATA_LIMIT = 65535
SENSORS = ("edge-sensor", "estate-sensor")
LOGS = {"edge-sensor": "edge-log/eve.json", "estate-sensor": "estate-log/eve.json", "waf": "waf-audit/audit.log"}


@dataclass(frozen=True)
class Slot:
    number: int
    estate: ipaddress.IPv4Network
    tag: str
    mtu: int

    @property
    def project(self) -> str:
        return f"s{self.number}"

    @property
    def prefix(self) -> str:
        return str(self.estate.network_address).rsplit(".", 1)[0]

    def container(self, service: str) -> str:
        return f"{self.project}-{service}"

    def network(self, key: str) -> str:
        return f"{self.project}_{key}"


def estate(base: str, number: int) -> ipaddress.IPv4Network:
    network = ipaddress.ip_network(base)
    if network.prefixlen > 16:
        raise RangeUnavailable(
            f"the estate network {base} is narrower than a /16; each slot takes its own /24 of it, "
            f"so set network.estate in cloud.yaml to a /16 such as 10.30.0.0/16")
    if not 1 <= number <= 255:
        raise RangeUnavailable(f"slot {number} has no /24 of {base}; a range host holds slots 1 to 255")
    return next(subnet for at, subnet in enumerate(network.subnets(new_prefix=24)) if at == number)


def _filled(text: str, slot: Slot) -> str:
    filled = TAG.sub(slot.tag, text)
    for name, value in (("slot", slot.number), ("estate", slot.prefix), ("mtu", slot.mtu)):
        filled = filled.replace(f"@{name}@", str(value))
    return filled


def _wargame_services(source: Path, wargames, slot: Slot, declared: dict,
                      contained: dict) -> tuple[dict, dict]:
    fronts = {str(name): str(octet) for name, octet in (declared.get("fronts") or {}).items()}
    limits = declared.get("limits") or {}
    extra = declared.get("extra_hosts") or {}
    services, networks = {}, {}
    for wargame in wargames:
        path = Path(source) / COMPOSE.format(wargame=wargame)
        if not path.is_file():
            raise RangeUnavailable(f"the range host runs {wargame!r} and {path} does not exist")
        backend = BACKEND.format(wargame=wargame)
        networks[backend] = {
            "internal": True,
            "driver_opts": {
                "com.docker.network.driver.mtu": str(slot.mtu),
                "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
            },
        }
        for name, service in (yaml.safe_load(path.read_text()).get("services") or {}).items():
            kept = {key: value for key, value in service.items() if key not in DROPPED}
            kept["image"] = TAG.sub(slot.tag, kept["image"])
            kept["container_name"] = slot.container(name)
            kept["hostname"] = name
            kept.update(contained)
            kept.update(limits.get(name) or {})
            attached = {backend: {}}
            if name in fronts:
                attached[FRONT] = {"ipv4_address": f"{slot.prefix}.{fronts[name]}"}
            if extra.get(name):
                kept["extra_hosts"] = list(extra[name])
            kept["networks"] = attached
            services[name] = kept
    return services, networks


class _Unaliased(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def dumped(document: dict) -> bytes:
    return yaml.dump(document, Dumper=_Unaliased, sort_keys=True).encode()


def compose(source: Path, slot: Slot, wargames) -> dict:
    document = yaml.safe_load(_filled((Path(source) / TEMPLATE).read_text(), slot))
    declared = document.pop("x-wargames", {}) or {}
    contained = dict(document.get("x-contained") or {})
    services, networks = _wargame_services(source, wargames, slot, declared, contained)
    clashing = sorted(set(services) & set(document.get("services") or {}))
    if clashing:
        raise RangeUnavailable(f"the wargames and the slot both define {', '.join(clashing)}")
    for service in (document.get("services") or {}).values():
        service.pop("build", None)
    document["services"] = {**document["services"], **services}
    document["networks"] = {**document["networks"], **networks}
    return document


def addressed(document: dict, network: str) -> dict[str, str]:
    return {
        name: str(attached["ipv4_address"])
        for name, service in (document.get("services") or {}).items()
        for key, attached in ((service.get("networks") or {}) if isinstance(service.get("networks"), dict) else {}).items()
        if key == network and isinstance(attached, dict) and attached.get("ipv4_address")
    }


def origin_addresses(cidr: str, count: int) -> list[str]:
    hosts = ipaddress.ip_network(cidr).hosts()
    return [str(address) for _, address in zip(range(9 + count), hosts)][9:]


def gateway_of(cidr: str) -> str:
    return str(next(ipaddress.ip_network(cidr).hosts()))


def kali_addresses(origins, default_origin: str) -> str:
    lines = [f"addr add {address}/{ipaddress.ip_network(origin.subnet).prefixlen} dev eth0"
             for origin in origins for address in origin_addresses(origin.subnet, origin.addresses)]
    by_id = {origin.id: origin for origin in origins}
    chosen = by_id.get(default_origin) or (origins[0] if origins else None)
    if chosen is not None:
        lines.append(f"route replace default via {gateway_of(chosen.subnet)} dev eth0")
    return "".join(f"{line}\n" for line in lines)


def edge_addresses(origins, slot: Slot) -> str:
    lines = [f"addr add {gateway_of(origin.subnet)}/{ipaddress.ip_network(origin.subnet).prefixlen} dev wan"
             for origin in origins]
    return "".join(f"{line}\n" for line in lines)


def sender(host: str, number: int) -> str:
    return host if number == 1 else f"{host}-{number}"


def forwarding(slot: Slot, collector: str, port: int, senders: dict[str, tuple[str, str]]) -> str:
    base = SLOT_FILES.format(slot=slot.number)
    blocks = []
    for service, (host, tag) in sorted(senders.items()):
        named = sender(host, slot.number)
        ruleset = f"cr-{slot.project}-{service}"
        blocks.append(
            f'template(name="{ruleset}" type="string" '
            f'string="<%PRI%>1 %TIMESTAMP:::date-rfc3339% {named} %APP-NAME% %PROCID% %MSGID% '
            f'%STRUCTURED-DATA% %msg%\\n")\n'
            f'input(type="imfile" File="{base}/{LOGS[service]}" Tag="{tag}" Facility="local2" '
            f'Severity="info" reopenOnTruncate="on" ruleset="{ruleset}")\n'
            f'ruleset(name="{ruleset}") {{\n'
            f'    action(type="omfwd" Target="{collector}" Port="{port}" Protocol="udp" '
            f'Template="{ruleset}")\n'
            '}\n'
        )
    return "".join(blocks)


def sensor_config(source: Path, path: str, slot: Slot, fronts: list[str]) -> str:
    filled = _filled((Path(source) / path).read_text(), slot)
    return filled.replace("@fronts@", " or ".join(f"host {address}" for address in fronts))


def slot_files(source: Path, slot: Slot, wargames, origins, default_origin: str,
               forwarded: str) -> dict[str, bytes]:
    document = compose(source, slot, wargames)
    fronts = front_addresses(document)
    return {
        "compose.yaml": dumped(document),
        "edge-sensor.yaml": sensor_config(source, EDGE_SENSOR, slot, fronts).encode(),
        "estate-sensor.yaml": sensor_config(source, ESTATE_SENSOR, slot, fronts).encode(),
        "kali.ip": kali_addresses(origins, default_origin).encode(),
        "edge.ip": edge_addresses(origins, slot).encode(),
        "rsyslog.conf": forwarded.encode(),
        "local.rules": (Path(source) / BASELINE_RULES).read_bytes(),
        "fronts": "".join(f"{name}\n" for name in sorted(fronted(document))).encode(),
        "gateway": f"{addressed(document, FRONT)['edge']}\n".encode(),
    }


def wargame_services(document: dict) -> set[str]:
    return {name for name, service in document["services"].items()
            if any(key.endswith("-default") for key in (service.get("networks") or {}))}


def fronted(document: dict) -> set[str]:
    return set(addressed(document, FRONT)) & wargame_services(document)


def front_addresses(document: dict) -> list[str]:
    return sorted(address for name, address in addressed(document, FRONT).items()
                  if name in wargame_services(document))


def archive(files: dict[str, bytes]) -> bytes:
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz", compresslevel=9) as tar:
        for member in sorted(files):
            info = tarfile.TarInfo(member)
            info.size = len(files[member])
            info.mode = 0o755 if member.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(files[member]))
    return packed.getvalue()


def digest(files: dict[str, bytes]) -> str:
    hashed = hashlib.sha256()
    for member in sorted(files):
        hashed.update(member.encode() + b"\0" + files[member] + b"\0")
    return hashed.hexdigest()[:16]


def images(source: Path, wargames, tag: str) -> list[str]:
    slot = Slot(number=1, estate=ipaddress.ip_network("10.30.1.0/24"), tag=tag, mtu=1500)
    document = compose(source, slot, wargames)
    return sorted({service["image"] for service in document["services"].values()})


def pristine(source: Path, wargames, tag: str, mtu: int) -> dict:
    slot = Slot(number=0, estate=ipaddress.ip_network("10.30.0.0/24"), tag=tag, mtu=mtu)
    document = compose(source, slot, wargames)
    kept = {name: service for name, service in document["services"].items()
            if name in wargame_services(document)}
    for name, service in kept.items():
        service["container_name"] = f"pristine-{name}"
        service["networks"] = {key: {} for key in service["networks"] if key.endswith("-default")}
    networks = {key: value for key, value in document["networks"].items() if key.endswith("-default")}
    return {"name": "pristine", "services": kept, "networks": networks}


def bundle(source: Path, wargames, tag: str, mtu: int) -> dict[str, bytes]:
    if not tag:
        raise RangeUnavailable("the range host pulls the images by the platform's own tag; set CR_IMAGE_TAG")
    if not mtu:
        raise RangeUnavailable("the range host gives its networks the tenant MTU; set CR_OPENSTACK_MTU "
                               "(network.mtu in cloud.yaml)")
    source = Path(source)
    return {
        "setup.sh": (source / SETUP).read_bytes(),
        "slot.sh": (source / SLOT_SCRIPT).read_bytes(),
        "images.txt": "".join(f"{image}\n" for image in images(source, wargames, tag)).encode(),
        "pristine.yaml": dumped(pristine(source, wargames, tag, mtu)),
        "wargames.txt": "".join(f"{name}\n" for name in pristine(source, wargames, tag, mtu)["services"]).encode(),
        "daemon.json": json.dumps({
            "mtu": mtu,
            "default-network-opts": {"bridge": {"com.docker.network.driver.mtu": str(mtu)}},
            "default-address-pools": [{"base": "10.40.0.0/16", "size": 28}],
            "log-driver": "local",
            "log-opts": {"max-size": "10m", "max-file": "2"},
        }, sort_keys=True).encode(),
    }


def user_data(files: dict[str, bytes]) -> str:
    script = (
        f"mkdir -p /var/lib/cr/bundle && tar -xzf /var/lib/cr/bundle.tar.gz -C /var/lib/cr/bundle "
        f"&& sh /var/lib/cr/bundle/setup.sh >/var/log/cr-setup.log 2>&1 "
        f"&& touch {READY} || {{ touch {FAILED}; tail -n 20 /var/log/cr-setup.log > /dev/console; }}"
    )
    document = {
        "write_files": [{
            "path": "/var/lib/cr/bundle.tar.gz",
            "encoding": "b64",
            "content": base64.b64encode(archive(files)).decode(),
        }],
        "runcmd": [["sh", "-c", script]],
    }
    encoded = base64.b64encode(("#cloud-config\n" + yaml.safe_dump(document)).encode()).decode()
    if len(encoded) > USER_DATA_LIMIT:
        raise RangeUnavailable(
            f"the range host needs {len(encoded)} bytes of user data and Nova takes at most "
            f"{USER_DATA_LIMIT}")
    return encoded


def exec_in(container: str, argv: list[str], reads_input: bool, tty: bool = False) -> list[str]:
    flags = ["-i"] if reads_input else []
    flags += ["-t"] if tty else []
    return ["sudo", "docker", "exec", *flags, container, *argv]


def up(slot: Slot) -> list[str]:
    return ["sudo", "sh", "-c",
            f"set -e; d={SLOT_FILES.format(slot=slot.number)}; mkdir -p \"$d\"; "
            f"base64 -d | tar -xzf - -C \"$d\"; exec sh {SCRIPT} up {slot.number}"]


def reset(slot: Slot) -> list[str]:
    return ["sudo", "sh", SCRIPT, "reset", str(slot.number)]


def down(slot: Slot) -> list[str]:
    return ["sudo", "sh", SCRIPT, "down", str(slot.number)]


def setup_state() -> list[str]:
    return ["sh", "-c", f"if [ -f {READY} ]; then echo ready; elif [ -f {FAILED} ]; then echo failed; "
                        f"tail -n 20 /var/log/cr-setup.log; else echo setting-up; fi"]


LISTED = (
    "docker network ls --filter label=com.docker.compose.project={project} --format '{{{{.Name}}}}' "
    "| while read -r n; do echo \"@network $n $(docker network inspect -f "
    "'{{{{range .IPAM.Config}}}}{{{{.Subnet}}}} {{{{end}}}}' \"$n\")\"; done\n"
    "for c in $(docker ps -q --filter label=com.docker.compose.project={project}); do\n"
    "  set -- $(docker inspect -f '{{{{index .Config.Labels \"com.docker.compose.service\"}}}} "
    "{{{{.State.Pid}}}} {{{{.HostConfig.NetworkMode}}}}' \"$c\")\n"
    "  [ \"$3\" = host ] && continue\n"
    "  echo \"@container $1\"\n"
    "  nsenter -t \"$2\" -n ip -o -4 addr show\n"
    "done"
)


def listed(project: str) -> list[str]:
    return ["sudo", "sh", "-c", LISTED.format(project=project)]
