from __future__ import annotations

import base64
import copy
import hashlib
import io
import ipaddress
import json
import re
import shlex
import tarfile
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from range import cloud
from range.ports import RangeUnavailable

ROLE = "wargames"
TEMPLATE = "deploy/range-host/slot.yaml"
SETUP = "deploy/range-host/setup.sh"
SLOT_SCRIPT = "deploy/range-host/slot.sh"
SENSOR_CONFIG = "deploy/suricata/suricata.yaml"
YAML_HEADER = "%YAML 1.1\n---\n"
BASELINE_RULES = "deploy/suricata/rules/local.rules"
COMPOSE = "wargames/{wargame}/compose.yaml"
INSTALLED = "/opt/cr"
SCRIPT = "slot.sh"
READY = "/var/lib/cr/ready"
FAILED = "/var/lib/cr/failed"
SLOT_FILES = f"{INSTALLED}/s{{slot}}"
TAG = re.compile(r"\$\{CR_IMAGE_TAG(?::-[^}]*)?\}")
DROPPED = ("build", "networks", "platform")
FRONT = "estate"
WEB = "web"
WEB_OFFSET = 128
BACKEND = "{wargame}-default"
INTERNET = "internet"
UP_TIMEOUT = 900.0
RESET_TIMEOUT = 600.0
USER_DATA_LIMIT = 65535
SENSOR = "sensor"
LOG_FILES = "/var/log/cr/s{slot}"
LOGS = {"sensor": "sensor/eve.json", "waf": "waf/audit.log"}
MGMT = "mgmt"
LOG_SERVER = "log-server"
SHIPPER = "{service}-shipper"
SHARED = re.compile(r"^service:(?P<service>\S+)$")
SHIPPED_PORT = 514
SHIPPING = "rsyslog"
UPLINK = "uplink"


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

    @property
    def web(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(f"{self.estate.network_address + WEB_OFFSET * 256}/24")

    @property
    def web_prefix(self) -> str:
        return str(self.web.network_address).rsplit(".", 1)[0]

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
    if not 1 <= number < WEB_OFFSET:
        raise RangeUnavailable(f"slot {number} has no /24 of {base}; a range host holds slots 1 to "
                               f"{WEB_OFFSET - 1}, and slot N's web servers take the /24 {WEB_OFFSET} above its own")
    return next(subnet for at, subnet in enumerate(network.subnets(new_prefix=24)) if at == number)


def _filled(text: str, slot: Slot) -> str:
    filled = TAG.sub(slot.tag, text)
    for name, value in (("slot", slot.number), ("estate", slot.prefix), ("web", slot.web_prefix),
                        ("mtu", slot.mtu)):
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
            if kept.get("healthcheck"):
                kept["healthcheck"] = {**kept["healthcheck"], **(declared.get("healthcheck") or {})}
            attached = {backend: {}}
            if name in fronts:
                attached[WEB] = {"ipv4_address": f"{slot.web_prefix}.{fronts[name]}"}
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


_rendered: dict[tuple, tuple[tuple, object]] = {}
_rendering = threading.Lock()


def _stamp(path: Path) -> tuple:
    try:
        found = path.stat()
    except OSError:
        return (str(path),)
    return (str(path), found.st_mtime_ns, found.st_size)


def _read_from(source: Path, wargames) -> tuple:
    return (_stamp(source / TEMPLATE), _stamp(source / SETUP),
            *(_stamp(source / COMPOSE.format(wargame=wargame)) for wargame in wargames))


def _kept(what: tuple, source: Path, wargames, make):
    read = _read_from(source, wargames)
    with _rendering:
        held = _rendered.get(what)
        if held is not None and held[0] == read:
            return held[1]
    made = make()
    with _rendering:
        _rendered[what] = (read, made)
    return made


def compose(source: Path, slot: Slot, wargames) -> dict:
    source, wargames = Path(source), tuple(wargames)
    return copy.deepcopy(_kept(("compose", str(source), slot, wargames), source, wargames,
                               lambda: _composed(source, slot, wargames)))


def bundle_digest(source: Path, wargames, tag: str, mtu: int) -> str:
    source, wargames = Path(source), tuple(wargames)
    return _kept(("bundle", str(source), wargames, tag, mtu), source, wargames,
                 lambda: digest(bundle(source, wargames, tag, mtu)))


def _composed(source: Path, slot: Slot, wargames) -> dict:
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


def shipped_from(document: dict, service: str) -> str:
    shipper = SHIPPER.format(service=service)
    shared = SHARED.match(str(document["services"][shipper].get("network_mode") or ""))
    return addressed(document, MGMT)[shared["service"] if shared else shipper]


def shipper_conf(slot: Slot, service: str, tag: str, server: str) -> str:
    return (
        'global(maxMessageSize="64k" workDirectory="/tmp")\n'
        'module(load="imfile")\n'
        f'input(type="imfile" File="{LOG_FILES.format(slot=slot.number)}/{LOGS[service]}" Tag="{tag}" '
        'Facility="local2" Severity="info" reopenOnTruncate="on")\n'
        f'action(type="omfwd" Target="{server}" Port="{SHIPPED_PORT}" Protocol="tcp" '
        'Template="RSYSLOG_SyslogProtocol23Format" action.resumeRetryCount="-1")\n'
    )


def forwarding(document: dict, slot: Slot, collector: str, port: int,
               senders: dict[str, tuple[str, str]]) -> dict[str, str]:
    server = addressed(document, MGMT)[LOG_SERVER]
    files, templates, relays = {}, [], []
    for service, (host, tag) in sorted(senders.items()):
        template = f"cr-{slot.project}-{service}"
        files[f"{SHIPPING}/{SHIPPER.format(service=service)}.conf"] = shipper_conf(slot, service, tag, server)
        templates.append(
            f'template(name="{template}" type="string" '
            f'string="<%PRI%>1 %TIMESTAMP:::date-rfc3339% {sender(host, slot.number)} {tag} %PROCID% %MSGID% '
            f'%STRUCTURED-DATA% %msg%\\n")\n'
        )
        relays.append(
            f'    if $fromhost-ip == "{shipped_from(document, service)}" then {{\n'
            f'        action(type="omfwd" Target="{collector}" Port="{port}" Protocol="udp" Template="{template}")\n'
            '        stop\n'
            '    }\n'
        )
    files[f"{SHIPPING}/{LOG_SERVER}.conf"] = (
        'global(maxMessageSize="64k")\n'
        'module(load="imtcp")\n'
        f'input(type="imtcp" port="{SHIPPED_PORT}" ruleset="relayed")\n'
        + "".join(templates)
        + 'ruleset(name="relayed") {\n' + "".join(relays) + '    stop\n}\n'
    )
    files[UPLINK] = f"{server} {collector} {port}\n"
    return files


def sniffed(document: dict) -> list[str]:
    return [str(attached["interface_name"])
            for attached in (document["services"][SENSOR].get("networks") or {}).values()
            if isinstance(attached, dict) and attached.get("interface_name") and not attached.get("ipv4_address")]


def sensor_config(source: Path, slot: Slot, document: dict) -> str:
    config = yaml.safe_load((Path(source) / SENSOR_CONFIG).read_text().removeprefix(YAML_HEADER))
    config["stats"] = {"enabled": True, "interval": 5}
    config["af-packet"] = [{
        "interface": interface,
        "cluster-id": int(f"{slot.number}{71 + at}"),
        "cluster-type": "cluster_flow",
        "defrag": True,
        "threads": 1,
    } for at, interface in enumerate(sniffed(document))]
    return YAML_HEADER + yaml.dump(config, Dumper=_Unaliased, sort_keys=False)


def slot_files(source: Path, slot: Slot, wargames, origins, default_origin: str,
               collector: str, port: int, senders: dict[str, tuple[str, str]]) -> dict[str, bytes]:
    document = compose(source, slot, wargames)
    shipped = forwarding(document, slot, collector, port, senders)
    return {
        **{name: text.encode() for name, text in shipped.items()},
        "compose.yaml": dumped(document),
        "sensor.yaml": sensor_config(source, slot, document).encode(),
        "kali.ip": kali_addresses(origins, default_origin).encode(),
        "edge.ip": edge_addresses(origins, slot).encode(),
        "local.rules": (Path(source) / BASELINE_RULES).read_bytes(),
        SCRIPT: (Path(source) / SLOT_SCRIPT).read_bytes(),
        "fronts": "".join(f"{name}\n" for name in sorted(fronted(document))).encode(),
        "gateway": f"{addressed(document, FRONT)['edge']}\n".encode(),
    }


def wargame_services(document: dict) -> set[str]:
    return {name for name, service in document["services"].items()
            if any(key.endswith("-default") for key in (service.get("networks") or {}))}


def fronted(document: dict) -> set[str]:
    return set(addressed(document, WEB)) & wargame_services(document)


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
        "images.txt": "".join(f"{image}\n" for image in images(source, wargames, tag)).encode(),
        "pristine.yaml": dumped(pristine(source, wargames, tag, mtu)),
        "wargames.txt": "".join(f"{name}\n" for name in pristine(source, wargames, tag, mtu)["services"]).encode(),
        "daemon.json": json.dumps({
            "mtu": mtu,
            "default-network-opts": {"bridge": {"com.docker.network.driver.mtu": str(mtu)}},
            "default-address-pools": [{"base": cloud.RANGE_HOST_POOL, "size": 28}],
            "log-driver": "local",
            "log-opts": {"max-size": "10m", "max-file": "2"},
            "userns-remap": "default",
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
            f"set -e; d={SLOT_FILES.format(slot=slot.number)}; mkdir -p \"$d\"; rm -rf \"$d/{SHIPPING}\"; "
            f"base64 -d | tar -xzf - -C \"$d\"; exec sh \"$d/{SCRIPT}\" up {slot.number}"]


def reset(slot: Slot) -> list[str]:
    return ["sudo", "sh", f"{SLOT_FILES.format(slot=slot.number)}/{SCRIPT}", "reset", str(slot.number)]


def standing(slot: Slot) -> list[str]:
    return ["test", "-f", f"{SLOT_FILES.format(slot=slot.number)}/compose.yaml"]


def down(slot: Slot) -> list[str]:
    return ["sudo", "sh", "-c", f"f={SLOT_FILES.format(slot=slot.number)}/{SCRIPT}; [ ! -f \"$f\" ] || exec sh \"$f\" down {slot.number}"]


def setup_state() -> list[str]:
    return ["sh", "-c", f"if [ -f {READY} ]; then echo ready; elif [ -f {FAILED} ]; then echo failed; "
                        f"tail -n 20 /var/log/cr-setup.log; else echo setting-up; fi"]


FORWARDING = f"{INSTALLED}/{{project}}/{SHIPPING}"
SNIFFS = re.compile(r"^--af-packet(=(?P<bridge>\S+))?$")
WIRING = r"""p=$1; f=$2
docker network ls --filter label=com.docker.compose.project=$p --format '{{.Name}}' | while read -r n; do
  echo "@network $n $(docker network inspect -f '{{.Id}} {{with index .Options "com.docker.network.bridge.name"}}{{.}}{{else}}-{{end}} {{range .IPAM.Config}}{{.Subnet}} {{end}}' "$n")"
done
for c in $(docker ps -q --filter label=com.docker.compose.project=$p); do
  set -- $(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}} {{.State.Pid}} {{.HostConfig.NetworkMode}}' "$c")
  echo "@container $1 $3"
  docker inspect -f '@args {{join .Args " "}}{{println}}{{range .Mounts}}@mount {{.Source}}{{println}}{{end}}{{range $n, $e := .NetworkSettings.Networks}}@leg {{$n}} {{$e.MacAddress}}{{println}}{{end}}' "$c"
  if [ "$3" = host ] || [ "${3#container:}" != "$3" ]; then :
  else nsenter -t "$2" -n sh -c 'ip -o link show; ip -o -4 addr show'
  fi
done
[ ! -d "$f" ] || sed -n 's/.*File="\([^"]*\)".*/@forward \1/p' "$f"/*-shipper.conf
[ ! -f "$f/log-server.conf" ] || sed -n 's/^input(type="im\([a-z]*\)" port="\([0-9]*\)".*/@port \2\/\1/p' "$f/log-server.conf"
[ ! -f "$f/log-server.conf" ] || sed -n 's/.*type="omfwd" Target="\([^"]*\)" Port="\([0-9]*\)" Protocol="\([a-z]*\)".*/@uplink \1:\2\/\3/p' "$f/log-server.conf" | head -n 1
"""


def wiring(project: str) -> list[str]:
    return ["sudo", "sh", "-c", WIRING, "sh", project, FORWARDING.format(project=project)]
