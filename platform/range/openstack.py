from __future__ import annotations

import base64
import ipaddress
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

import requests

from range import clock, fabric, interfaces, rangehost, slot
from range.declared import Declaration
from rules import suricata
from range.ports import (
    Drifted, Node, Ran, RangeUnavailable, Segment, Sensor, Shape, execute,
    reported, reporting,
)

NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags-any={tags}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"
BOOT = "POST {nova}/servers"
PROJECT_NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}"
PROJECT_SUBNETS = "GET {neutron}/v2.0/subnets?project_id={project}"
PORTS = "GET {neutron}/v2.0/ports?network_id={network}"
PROJECT_PORTS = "GET {neutron}/v2.0/ports?project_id={project}"
CREATE_NETWORK = "POST {neutron}/v2.0/networks"
TAG_NETWORK = "PUT {neutron}/v2.0/networks/{network}/tags"
CREATE_SUBNETS = "POST {neutron}/v2.0/subnets"
DELETE_SUBNET = "DELETE {neutron}/v2.0/subnets/{subnet}"
NO_RESOLVER = "0.0.0.0"
DELETE_NETWORK = "DELETE {neutron}/v2.0/networks/{network}"
KEYPAIRS = "GET {nova}/os-keypairs"
IMPORT_KEYPAIR = "POST {nova}/os-keypairs"
DELETE_KEYPAIR = "DELETE {nova}/os-keypairs/{keypair}"
IMAGES = "GET {glance}/v2/images?name={name}"
OWN_IMAGES = "GET {glance}/v2/images?owner={project}&visibility=private&limit=100"
DELETE_IMAGE = "DELETE {glance}/v2/images/{image}"
FLAVORS = "GET {nova}/flavors"
DELETE_SERVER = "DELETE {nova}/servers/{server}"
SECURITY_GROUPS = "GET {neutron}/v2.0/security-groups?project_id={project}"
CREATE_GROUP = "POST {neutron}/v2.0/security-groups"
CREATE_RULE = "POST {neutron}/v2.0/security-group-rules"
DELETE_GROUP = "DELETE {neutron}/v2.0/security-groups/{group}"
DELETE_RULE = "DELETE {neutron}/v2.0/security-group-rules/{rule}"
CREATE_PORT = "POST {neutron}/v2.0/ports"
DELETE_PORT = "DELETE {neutron}/v2.0/ports/{port}"
ATTACH = "POST {nova}/servers/{server}/os-interface"
INTERFACES = "GET {nova}/servers/{server}/os-interface"
DETACH = "DELETE {nova}/servers/{server}/os-interface/{port}"

DELETES = {
    "subnet": DELETE_SUBNET, "network": DELETE_NETWORK, "keypair": DELETE_KEYPAIR,
    "group": DELETE_GROUP, "port": DELETE_PORT, "server": DELETE_SERVER, "image": DELETE_IMAGE,
}

FIXED = "OS-EXT-IPS:type"
LAUNCHED = "OS-SRV-USG:launched_at"
PAGE_LIMIT = 50
BUILDS = "cr_image"
SETTING_UP = "SETTING_UP"
SETUP_FAILED = "SETUP_FAILED"

CONNECT_TIMEOUT = 10
SERVER_ALIVE_INTERVAL = 15
SERVER_ALIVE_COUNT_MAX = 3
SHARED_CONNECTIONS = "/tmp/cr-ssh-%C"
SHARED_FOR = 60
NOVA_MICROVERSION = "2.1"
SUBJECT_TOKEN = "X-Subject-Token"
SEGMENT_TAG = fabric.TAG
ATTACKER_ROLE = "attacker"
SCORER_ROLE = "scorer"
GATEWAY_ROLE = "gateway"
SENSOR_ROLES = ("sensor", "estate-sensor")
OWN_LISTED_TIMEOUT = 60
GONE_WAIT = 300
GONE_POLL = 3
COLLECTED = {"edge-sensor": ("sensor", "suricata"), "estate-sensor": ("estate-sensor", "suricata"),
             "waf": (GATEWAY_ROLE, "modsecurity")}

SETTINGS = {
    "keystone": "CR_OPENSTACK_KEYSTONE",
    "user": "CR_OPENSTACK_USER",
    "domain": "CR_OPENSTACK_DOMAIN",
    "password": "CR_OPENSTACK_PASSWORD",
    "project": "CR_OPENSTACK_PROJECT",
    "ssh_user": "CR_OPENSTACK_SSH_USER",
    "ssh_key": "CR_OPENSTACK_SSH_KEY",
    "region": "CR_OPENSTACK_REGION",
    "interface": "CR_OPENSTACK_INTERFACE",
    "source": "CR_SOURCE",
    "base_image": "CR_OPENSTACK_BASE_IMAGE",
    "flavor": "CR_OPENSTACK_FLAVOR",
    "availability_zone": "CR_OPENSTACK_AVAILABILITY_ZONE",
    "subnets": "CR_OPENSTACK_SUBNETS",
    "mtu": "CR_OPENSTACK_MTU",
    "build_network": "CR_OPENSTACK_BUILD_NETWORK",
    "platform": "CR_OPENSTACK_PLATFORM",
    "image_tag": "CR_IMAGE_TAG",
    "slots": "CR_OPENSTACK_SLOTS",
}

_connected: dict[tuple, tuple["Cloud", object]] = {}
_set_up: set[str] = set()
_booting = threading.Lock()


class EndpointGone(RangeUnavailable):
    pass


def pairs(text: str) -> dict[str, str]:
    found = {}
    for word in (text or "").split():
        key, equals, value = word.partition("=")
        if not equals or not key or not value:
            raise ValueError(f"{word!r} is not key=value")
        found[key] = value
    return found


def connect(
    declared: Declaration,
    keystone: str = "",
    user: str = "",
    password: str = "",
    project: str = "",
    ssh_user: str = "",
    ssh_key: str = "",
    region: str = "",
    interface: str = "",
    domain: str = "",
    source: str = "",
    base_image: str = "",
    flavor: str = "",
    availability_zone: str = "",
    subnets: str = "",
    mtu: str = "",
    build_network: str = "",
    platform: str = "",
    image_tag: str = "",
    slots: str = "",
) -> "OpenStack":
    given = {
        "keystone": keystone, "user": user, "password": password,
        "project": project, "ssh_user": ssh_user, "ssh_key": ssh_key,
        "region": region, "interface": interface, "domain": domain,
    }
    missing = [SETTINGS[name] for name, value in given.items() if not value]
    if missing:
        raise RangeUnavailable(
            f"the OpenStack substrate reaches no cloud without "
            f"{', '.join(missing)}"
        )
    known = (keystone, user, password, project, ssh_user, ssh_key,
             region, interface, domain)

    def rediscover() -> tuple[Cloud, object]:
        cloud = discover(
            keystone, user, password, project, ssh_user, ssh_key,
            region=region, interface=interface, domain=domain,
        )
        _connected[known] = (cloud, http_reader(cloud, password))
        return _connected[known]

    try:
        build = Build(
            source=source, base_image=base_image, flavor=flavor,
            availability_zone=availability_zone, inside=pairs(subnets),
            mtu=int(mtu or 0), network=build_network, platform=platform, image_tag=image_tag,
            slots=_count(slots or "1"),
        )
    except ValueError as error:
        raise RangeUnavailable(
            f"the cloud settings ({', '.join(SETTINGS[n] for n in ('subnets', 'mtu', 'slots'))}) "
            f"do not parse: {error}; they come from cloud.yaml through the Heat stack"
        ) from error
    cloud, reader = _connected.get(known) or rediscover()
    return OpenStack(declared, cloud, get=reader, rediscover=rediscover, build=build)


def _count(text: str) -> int:
    count = int(text)
    if count < 1:
        raise ValueError(f"{SETTINGS['slots']} is {count}; a range has one slot or more")
    return count


def alongside(*chains: list) -> list:
    def in_order(chain: list) -> list:
        return [step() for step in chain]

    with ThreadPoolExecutor(max_workers=max(1, len(chains))) as pool:
        running = [pool.submit(in_order, chain) for chain in chains]
        wait(running)
    return [done for finished in running for done in finished.result()]


def forget() -> None:
    _connected.clear()
    _set_up.clear()


def discover(
    keystone: str,
    user: str,
    password: str,
    project: str,
    ssh_user: str,
    ssh_key: str,
    region: str = "RegionOne",
    interface: str = "public",
    timeout: float = 30.0,
    domain: str = "default",
) -> "Cloud":
    answered = _signed_in(keystone, user, password, project, timeout, domain)

    catalog = (answered.json().get("token") or {}).get("catalog") or []
    return Cloud(
        keystone=keystone,
        neutron=_endpoint(catalog, "network", region, interface),
        nova=_endpoint(catalog, "compute", region, interface),
        glance=_endpoint(catalog, "image", region, interface),
        project=project,
        user=user,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        domain=domain,
    )


def _signed_in(keystone: str, user: str, password: str, project: str, timeout: float,
               domain: str = "default"):
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": user,
                        "domain": {"id": domain},
                        "password": password,
                    }
                },
            },
            "scope": {"project": {"id": project}},
        }
    }
    answered = _send("post", f"{keystone}/v3/auth/tokens", None, body, timeout)
    if not answered.ok:
        raise RangeUnavailable(
            f"{keystone} refused the credentials with "
            f"{answered.status_code}: {answered.text.strip()[:200]}"
        )
    return answered


def _endpoint(catalog, service: str, region: str, interface: str) -> str:
    for entry in catalog:
        if entry.get("type") != service:
            continue
        for endpoint in entry.get("endpoints") or []:
            if (endpoint.get("interface") == interface
                    and endpoint.get("region_id") == region):
                return endpoint.get("url") or ""
    raise RangeUnavailable(
        f"the token's catalogue has no {service!r} endpoint with interface "
        f"{interface!r} in region {region!r}; set {SETTINGS['region']} and "
        f"{SETTINGS['interface']} to a region and interface it lists"
    )


def http_reader(cloud: "Cloud", password: str, timeout: float = 30.0):
    held: dict = {"token": ""}

    def authenticate() -> str:
        answered = _signed_in(
            cloud.keystone, cloud.user, password, cloud.project, timeout, cloud.domain
        )
        held["token"] = answered.headers.get(SUBJECT_TOKEN, "")
        if not held["token"]:
            raise RangeUnavailable(
                f"{cloud.keystone} issued no {SUBJECT_TOKEN}, so nothing can "
                f"be asked of this cloud"
            )
        return held["token"]

    def send(call: str, body=None) -> dict:
        verb, _, url = call.partition(" ") if " " in call else ("GET", "", call)
        token = held["token"]
        if not token:
            token = authenticate()
        answered = _send(verb.lower(), url, token, body, timeout)
        if answered.status_code == 401:
            answered = _send(verb.lower(), url, authenticate(), body, timeout)
        if not answered.ok:
            refused = EndpointGone if answered.status_code == 404 else RangeUnavailable
            raise refused(
                f"{verb} {url} answered {answered.status_code}: "
                f"{answered.text.strip()[:200]}"
            )
        return answered.json() if answered.content else {}

    return send


def _send(verb: str, url: str, token: str | None, body, timeout: float):
    headers = {"X-OpenStack-Nova-API-Version": NOVA_MICROVERSION}
    if token:
        headers["X-Auth-Token"] = token
    try:
        return getattr(requests, verb)(
            url, headers=headers, json=body, timeout=timeout
        )
    except requests.RequestException as exc:
        raise EndpointGone(f"could not reach {url}: {exc}") from exc


def _one_ipv4_subnet(segment_id: str, allocated: list[dict]) -> dict:
    ipv4 = [subnet for subnet in allocated if subnet.get("ip_version", 4) == 4]
    if len(ipv4) > 1:
        raise RangeUnavailable(
            f"segment {segment_id!r} has {len(ipv4)} IPv4 subnets "
            f"{[subnet.get('cidr', '') for subnet in ipv4]}; alerts are binned "
            f"by one subnet per segment, so give its network exactly one IPv4 subnet"
        )
    return ipv4[0] if ipv4 else {}


def _subnet_body(subnet: "fabric.Subnet", network_id: str) -> dict:
    body = {
        "network_id": network_id, "name": subnet.name, "cidr": subnet.cidr,
        "ip_version": 4, "enable_dhcp": subnet.dhcp, "dns_nameservers": [NO_RESOLVER],
    }
    if not subnet.gateway:
        body["gateway_ip"] = None
    return body


def _tidied(piped: subprocess.Popen, scratch: Path) -> None:
    piped.wait()
    shutil.rmtree(scratch, ignore_errors=True)


def _detached(port: dict) -> bool:
    return not port.get("device_id") and not port.get("device_owner")


def _generations(servers: list[dict]) -> dict[str, str]:
    found = {}
    for server in servers:
        if not server.get("id"):
            continue
        booted = "".join(c for c in str(server.get(LAUNCHED) or "") if c.isdigit())
        generation = "-".join(filter(None, ("cr", server["id"], booted)))
        for entries in (server.get("addresses") or {}).values():
            for entry in entries:
                if entry.get(FIXED) == "fixed":
                    found[entry["addr"]] = generation
    return found


@dataclass(frozen=True)
class Cloud:
    keystone: str
    neutron: str
    nova: str
    project: str
    user: str
    ssh_user: str
    ssh_key: str
    ssh_config: str = ""
    glance: str = ""
    domain: str = "default"


@dataclass(frozen=True)
class Build:
    source: str = ""
    base_image: str = ""
    flavor: str = ""
    availability_zone: str = ""
    inside: dict = field(default_factory=dict)
    mtu: int = 0
    network: str = ""
    platform: str = ""
    image_tag: str = ""
    slots: int = 1

    def placed(self, server: dict) -> dict:
        return {**server, "availability_zone": self.availability_zone} if self.availability_zone else server


class OpenStack:
    def __init__(
        self, declared: Declaration, cloud: Cloud, get, rediscover=None,
        build: Build = Build(), slot: int = 1,
    ):
        self.declared = declared
        self.cloud = cloud
        self.build = build
        self.get = get
        self.rediscover = rediscover
        self.slot = slot
        self._shape: Shape | None = None
        self._generations: dict[str, str] = {}
        self._range_address = ""

    @property
    def slots(self) -> int:
        return max(1, self.build.slots)

    @property
    def max_sessions(self) -> int:
        return self.slots

    def in_slot(self, number: int) -> "OpenStack":
        if not 1 <= number <= self.slots:
            raise RangeUnavailable(
                f"slot {number} is not one of the {self.slots} slot(s) the cloud settings ask for"
            )
        return OpenStack(self.declared, self.cloud, self.get, self.rediscover, self.build, slot=number)

    def every_slot(self) -> list["OpenStack"]:
        return [self.in_slot(number) for number in range(1, self.slots + 1)]

    @property
    def range_host(self) -> str:
        return self.declared.range_host

    def _wargames(self) -> tuple[str, ...]:
        return self.declared.hosts[self.range_host].wargames

    def _laid_out(self) -> rangehost.Slot:
        base = self.build.inside.get(slot.NAMED_ON)
        if not base:
            raise RangeUnavailable(
                f"the slots' estates are carved from network.{slot.NAMED_ON} in cloud.yaml, "
                f"which {SETTINGS['subnets']} does not carry")
        return rangehost.Slot(number=self.slot, estate=rangehost.estate(base, self.slot),
                              tag=self.build.image_tag, mtu=self.build.mtu or 1500)

    def _document(self) -> dict:
        return rangehost.compose(Path(self.build.source), self._laid_out(), self._wargames())

    def _service_hosts(self) -> dict[str, str]:
        found = {}
        for role, service in sorted(self.declared.compose.items()):
            host = self.declared.roles[role]
            found.setdefault(service, service if self.declared.hosts[host].wargames else host)
        return found

    def describe(self) -> Shape:
        shape = self._shape
        if shape is None:
            try:
                shape = self._read()
            except EndpointGone:
                if self.rediscover is None:
                    raise
                self.cloud, self.get = self.rediscover()
                shape = self._read()
            self._shape = shape
        return shape

    def segments(self) -> tuple[Segment, ...]:
        return self.describe().segments

    def host_key_alias(self, address: str) -> str:
        self.describe()
        return self._generations.get(address, "")

    def _read(self) -> Shape:
        carriers = fabric.carried(self.declared)
        wanted = ",".join(f"{SEGMENT_TAG}={carrier}" for carrier in carriers)
        bound = fabric.bound(self.declared, self._all(NETWORKS, "networks", tags=wanted))
        servers = self._all(SERVERS, "servers")
        self._generations = _generations(servers)
        standing = {slot.known_as(server) for server in servers}
        origins = {origin.id: origin for origin in self.declared.origins}
        in_slot = any(s.id in origins or s.id == slot.NAMED_ON for s in self.declared.segments)
        laid = self._laid_out() if in_slot else None
        on_estate = rangehost.addressed(self._document(), rangehost.FRONT) if in_slot else {}
        names = self._service_hosts()
        edge = self.declared.roles.get("edge", "")
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")
        gateway = on_estate.get(self.declared.compose.get("edge", ""), "")

        segments = []
        for declared in self.declared.segments:
            origin = origins.get(declared.id)
            if origin is not None:
                way_in = rangehost.gateway_of(origin.subnet)
                nodes = [Node(name=edge, address=way_in)] + [
                    Node(name=attacker, address=address)
                    for address in rangehost.origin_addresses(origin.subnet, origin.addresses)]
                segments.append(replace(declared, subnet=origin.subnet, network=laid.network(rangehost.INTERNET),
                                        gateway=way_in, nodes=tuple(sorted(nodes, key=lambda n: n.name))))
            elif declared.id == slot.NAMED_ON:
                nodes = [Node(name=names.get(service, service), address=address)
                         for service, address in sorted(on_estate.items())]
                segments.append(replace(declared, subnet=str(laid.estate), network=laid.network(rangehost.FRONT),
                                        gateway=gateway, nodes=tuple(sorted(nodes, key=lambda n: n.name))))
            elif declared.id in carriers:
                network = bound.get(declared.id)
                if network is None:
                    raise RangeUnavailable(
                        f"the declaration names the segment {declared.id!r} and no network of "
                        f"project {self.cloud.project!r} is tagged {SEGMENT_TAG}={declared.id}")
                held = _one_ipv4_subnet(declared.id, self._all(SUBNETS, "subnets", network=network["id"]))
                segments.append(replace(declared, subnet=held.get("cidr", ""), network=network["id"],
                                        gateway=held.get("gateway_ip") or "",
                                        nodes=self._nodes(network["name"], servers, held.get("cidr", ""))))
            else:
                raise RangeUnavailable(f"the declaration names the segment {declared.id!r}, which "
                                       f"neither a slot nor the fabric carries")
        sensors = tuple(Sensor(name=name, watches=host) for name, host in self.declared.watching()
                        if self.range_host in standing)
        return Shape(segments=tuple(segments), sensors=sensors)

    def _nodes(self, network_name: str, servers: list[dict], cidr: str = "") -> tuple[Node, ...]:
        inside = ipaddress.ip_network(cidr) if cidr else None
        found = [
            Node(name=slot.known_as(server), address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(network_name, [])
            if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4
            and (inside is None or ipaddress.ip_address(entry["addr"]) in inside)
        ]
        return tuple(sorted(found, key=lambda node: node.name))

    def _address(self, host: str) -> str:
        for segment in self.describe().segments:
            if segment.id != fabric.MANAGEMENT:
                continue
            for node in segment.nodes:
                if node.name == host:
                    return node.address
        raise RangeUnavailable(f"{host} stands on no {fabric.MANAGEMENT} address this platform can reach")

    def address(self, role: str) -> str:
        host = self.declared.host(role)
        return self._address(self.range_host if host in self._contained_hosts() else host)

    def _contained_hosts(self) -> set[str]:
        return {self.declared.roles[role] for role in self.declared.compose} - {self.range_host}

    def _container(self, role: str) -> str:
        service = self.declared.compose.get(role, "")
        return self._laid_out().container(service) if service else ""

    def runner(self, role: str, segment_id: str = ""):
        host = self.declared.host(role)
        container = self._container(role)
        if not container and host != self.range_host:
            raise RangeUnavailable(f"{role!r} is filled by {host}, which runs no command the range host reaches")
        return self._shell(container)

    def _shell(self, container: str = ""):
        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            address = self._address(self.range_host)
            with tempfile.TemporaryDirectory() as scratch:
                said = Path(scratch) / "ssh.log"
                config = self._config(Path(scratch) / "ssh_config", address)
                command = self._ssh(address, stdin is not None, said, config)
                sent = reporting(argv)
                if container:
                    sent = rangehost.exec_in(container, sent, stdin is not None)
                command.append(shlex.join(sent))
                done = execute(self.range_host, command, stdin, timeout)
                logged = said.read_text() if said.exists() else ""
                complaint = " ".join(filter(None, (
                    line.strip("@ ") for line in
                    f"{logged}\n{done.stderr or ''}".splitlines()
                )))
            ran = reported(done)
            if ran is None:
                raise RangeUnavailable(
                    f"{container or self.range_host} at {address} never reported the command finishing: "
                    + (complaint[:1000] or "the connection ended before it did")
                )
            return ran

        return run

    def terminal(self, host: str) -> tuple[str, str, str]:
        role = next((role for role, filled in sorted(self.declared.roles.items())
                     if filled == host and role in self.declared.compose), "")
        if not role:
            raise RangeUnavailable(f"{host} has no container in the slot to open a terminal in")
        address = self._address(self.range_host)
        return address, self._generations.get(address, "") or address, self._container(role)

    def interfaces(self, hosts=None, skip_unanswered=True) -> list[interfaces.Interface]:
        origins = {origin.id: origin.segment for origin in self.declared.origins}
        subnets = [(segment.subnet, origins.get(segment.id, segment.id)) for segment in self.describe().segments]
        found = []
        try:
            listed = self._shell()(rangehost.listed(self._laid_out().project), timeout=60).output
        except RangeUnavailable:
            if not skip_unanswered:
                raise
            listed = ""
        names = self._service_hosts()
        project = self._laid_out().project
        networks, inside = interfaces.slot_listed(listed, project)
        unanswered = sorted(name for name, service in self._document()["services"].items()
                            if service.get("networks") and name not in inside)
        if unanswered and not skip_unanswered:
            raise RangeUnavailable(f"{', '.join(unanswered)} did not answer in slot {self.slot}")
        here = subnets + [(subnet, key) for key, subnet in networks
                          if key not in (rangehost.INTERNET, rangehost.FRONT)]
        for service, said in sorted(inside.items()):
            host = names.get(service, service)
            if hosts is None or host in hosts:
                found += interfaces.placed(host, said, here)
        scorer = self.declared.host(SCORER_ROLE)
        if hosts is not None and scorer in hosts:
            found += interfaces.placed(scorer, self._own_listed(), subnets)
        return found

    @staticmethod
    def _own_listed() -> str:
        try:
            done = subprocess.run(interfaces.on_this_host(interfaces.LISTED), capture_output=True, text=True,
                                  timeout=OWN_LISTED_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout if done.returncode == 0 else ""

    def _ssh(self, address: str, reads_input: bool, log: Path, config: Path) -> list[str]:
        command = ["ssh", "-F", str(config)]
        if not reads_input:
            command.append("-n")
        return command + [
            "-i", self.cloud.ssh_key,
            "-E", str(log),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "LogLevel=ERROR",
            f"{self.cloud.ssh_user}@{address}",
        ]

    def _config(self, written: Path, address: str) -> Path:
        included = []
        if self.cloud.ssh_config:
            linked = written.with_name("deployment_ssh_config")
            linked.symlink_to(Path(self.cloud.ssh_config).expanduser().resolve())
            included.append(f'Include "{linked}"')
        defaults = [
            "Host *",
            "  BatchMode yes",
            "  LogLevel ERROR",
            "  StrictHostKeyChecking accept-new",
            f"  ConnectTimeout {CONNECT_TIMEOUT}",
            f"  ServerAliveInterval {SERVER_ALIVE_INTERVAL}",
            f"  ServerAliveCountMax {SERVER_ALIVE_COUNT_MAX}",
            "  ControlMaster auto",
            f"  ControlPath {SHARED_CONNECTIONS}",
            f"  ControlPersist {SHARED_FOR}",
        ]
        generation = self._generations.get(address)
        aliased = [f"Host {address}", f"  HostKeyAlias {generation}"] if generation else []
        written.write_text("\n".join(included + aliased + defaults) + "\n")
        return written

    def launcher(self, segment_id: str):
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")

        def launch(image: str, argv: list[str], timeout: float = 600.0) -> Ran:
            if image != attacker:
                raise RangeUnavailable(
                    f"asked to start {image!r} on {segment_id!r}; a tool runs in the slot's "
                    f"attacker {attacker!r} and no other container"
                )
            return self.runner(ATTACKER_ROLE)(argv, timeout=timeout)

        return launch

    def users_box(self, segment_ids: list[str], image: str):
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")
        if image != attacker:
            raise RangeUnavailable(
                f"asked to run customers from {image!r}; they run in the slot's attacker "
                f"{attacker!r}, which stands on every origin"
            )
        return self.runner(ATTACKER_ROLE)

    def opened(self, role: str, argv: list[str]) -> socket.socket:
        address = self._address(self.range_host)
        container = self._container(role)
        scratch = Path(tempfile.mkdtemp())
        config = self._config(scratch / "ssh_config", address)
        command = self._ssh(address, True, scratch / "ssh.log", config)
        sent = rangehost.exec_in(container, argv, True) if container else argv
        ours, theirs = socket.socketpair()
        try:
            piped = subprocess.Popen(command + [shlex.join(sent)], stdin=theirs, stdout=theirs,
                                     stderr=subprocess.DEVNULL)
        except OSError as exc:
            ours.close()
            shutil.rmtree(scratch, ignore_errors=True)
            raise RangeUnavailable(f"could not reach {self.range_host}: {exc}") from exc
        finally:
            theirs.close()
        threading.Thread(target=_tidied, args=(piped, scratch), daemon=True).start()
        return ours

    def plan_fabric(self) -> fabric.Plan:
        networks, subnets, keypairs, groups = self._fabric_standing()
        return fabric.plan(self.declared, networks, subnets, keypairs, self._public_key(),
                           groups, self._reached(networks), self.build.inside)

    def ensure_fabric(self) -> fabric.Plan:
        public_key = self._public_key(make=True)
        networks, subnets, keypairs, groups = self._fabric_standing()
        plan = fabric.plan(self.declared, networks, subnets, keypairs, public_key,
                           groups, self._reached(networks), self.build.inside)
        if plan.drifted:
            raise Drifted("; ".join(plan.drifted))
        carriers = {segment: network["id"] for segment, network in fabric.bound(self.declared, networks).items()}
        carriers.update({segment: self._make_network(segment) for segment in plan.networks})
        if plan.subnets:
            self.get(self._call(CREATE_SUBNETS), {"subnets": [
                _subnet_body(subnet, carriers[subnet.segment]) for subnet in plan.subnets
            ]})
        if plan.keypair:
            self.get(self._call(IMPORT_KEYPAIR), {
                "keypair": {"name": fabric.KEYPAIR, "public_key": public_key}
            })
        named = {group["name"]: group["id"] for group in groups}
        for name in plan.groups:
            named[name] = self.get(self._call(CREATE_GROUP), {
                "security_group": {"name": name}
            })["security_group"]["id"]
            if name == fabric.MANAGEMENT_GROUP:
                self.get(self._call(CREATE_RULE), {"security_group_rule": {
                    "security_group_id": named[name], "direction": "ingress",
                    "ethertype": "IPv4", "remote_group_id": named[fabric.REACH_GROUP],
                }})
        if plan.ntp:
            self.get(self._call(CREATE_RULE), {"security_group_rule": fabric.ntp_rule(
                named[fabric.REACH_GROUP], named[fabric.MANAGEMENT_GROUP])})
        if plan.reach:
            self._attach(carriers[fabric.MANAGEMENT], named[fabric.REACH_GROUP])
        self._shape = None
        return plan

    def _reached(self, networks: list) -> bool:
        if not self.build.platform:
            return True
        management = fabric.bound(self.declared, networks).get(fabric.MANAGEMENT)
        return management is not None and any(
            port.get("device_id") == self.build.platform
            for port in self._all(PORTS, "ports", network=management["id"])
        )

    def _attach(self, network: str, group: str) -> None:
        name = f"{fabric.KEYPAIR}.{fabric.MANAGEMENT}"
        for left in self._all(PORTS, "ports", network=network):
            if left.get("name") == name and _detached(left):
                self.get(self._call(DELETE_PORT, port=left["id"]))
        port = self.get(self._call(CREATE_PORT), {"port": {
            "network_id": network, "name": name, "security_groups": [group],
        }})["port"]["id"]
        try:
            self.get(self._call(ATTACH, server=self.build.platform), {
                "interfaceAttachment": {"port_id": port}
            })
        except RangeUnavailable:
            self.get(self._call(DELETE_PORT, port=port))
            raise

    def teardown_fabric(self) -> list[tuple[str, str]]:
        networks, subnets, keypairs, groups = self._fabric_standing()
        own = []
        for network in networks:
            if fabric.segment_of(network) is None:
                continue
            ports = self._all(PORTS, "ports", network=network["id"])
            servers = [port for port in ports if str(port.get("device_owner") or "").startswith("compute:")]
            own += [("port", p["id"]) for p in ports if _detached(p)]
            own += [("port", p["id"]) for p in servers if p.get("device_id") == self.build.platform]
            standing = [p for p in servers if p.get("device_id") != self.build.platform]
            if standing:
                raise RangeUnavailable(
                    f"{len(standing)} server port(s) still stand on "
                    f"{network['name']}; delete those servers first"
                )
        steps = own + fabric.teardown(self.declared, networks, subnets, keypairs, groups)
        for kind, ident in steps:
            self.get(self._call(DELETES[kind], **{kind: ident}))
        self._shape = None
        return steps

    def _make_network(self, segment: str) -> str:
        created = self.get(self._call(CREATE_NETWORK), {
            "network": {"name": fabric.network_name(segment)}
        })["network"]
        try:
            self.get(self._call(TAG_NETWORK, network=created["id"]), {
                "tags": fabric.network_tags(segment)
            })
        except RangeUnavailable:
            self.get(self._call(DELETE_NETWORK, network=created["id"]))
            raise
        return created["id"]

    def _fabric_standing(self) -> tuple[list, list, list, list]:
        return (
            self._all(PROJECT_NETWORKS, "networks"),
            self._all(PROJECT_SUBNETS, "subnets"),
            [
                entry["keypair"]
                for entry in self.get(self._call(KEYPAIRS)).get("keypairs") or []
            ],
            self._all(SECURITY_GROUPS, "security_groups"),
        )

    def _public_key(self, make: bool = False) -> str:
        private = Path(self.cloud.ssh_key).expanduser()
        public = private.with_name(private.name + ".pub")
        if make and not private.exists():
            private.parent.mkdir(parents=True, exist_ok=True)
            made = subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                 fabric.KEYPAIR, "-f", str(private)],
                capture_output=True, text=True,
            )
            if made.returncode != 0:
                raise RangeUnavailable(
                    f"ssh-keygen could not make {private}: {made.stderr.strip()[:200]}"
                )
        return public.read_text().strip() if public.exists() else ""

    def _bundle(self) -> dict[str, bytes]:
        return rangehost.bundle(Path(self.build.source), self._wargames(), self.build.image_tag,
                                self.build.mtu)

    def _range_server(self, servers: list[dict]) -> dict | None:
        return next((server for server in servers if slot.host_of(server) == self.range_host), None)

    def _setup_status(self, server: dict) -> str:
        if server.get("status") != "ACTIVE" or server["id"] in _set_up:
            return str(server.get("status") or "")
        try:
            said = self._shell()(rangehost.setup_state(), timeout=30).output
        except RangeUnavailable:
            return SETTING_UP
        if said.startswith("ready"):
            self._close_egress(server["id"])
            _set_up.add(server["id"])
            return "ACTIVE"
        return SETUP_FAILED if said.startswith("failed") else SETTING_UP

    def _close_egress(self, server: str) -> None:
        attached = self.get(self._call(INTERFACES, server=server)).get("interfaceAttachments") or []
        for interface in attached:
            if interface.get("net_id") == self.build.network:
                self.get(self._call(DETACH, server=server, port=interface["port_id"]))

    def _plan(self, servers: list[dict], digest: str, statuses: dict[str, str]) -> slot.Plan:
        server = self._range_server(servers)
        if server is None:
            return slot.Plan(boot=(self.range_host,), blocked=tuple(self._unbootable()), slot=self.slot)
        metadata = server.get("metadata") or {}
        stale = (metadata.get(slot.TAG) != self.build.image_tag or metadata.get(slot.BUNDLE) != digest)
        return slot.Plan(standing=((self.range_host, server["id"], statuses[server["id"]]),),
                         slot=self.slot, stale=(self.range_host,) if stale else ())

    def _unbootable(self) -> list[str]:
        reasons = []
        if not self.build.network:
            reasons.append(f"the range host pulls its images, so it needs a network that reaches the "
                           f"Internet; set {SETTINGS['build_network']}")
        if not self.build.image_tag:
            reasons.append(f"the range host pulls the images by the platform's tag; set {SETTINGS['image_tag']}")
        return reasons

    def plan_slot(self) -> slot.Plan:
        return self.plan_slots()[self.slot - 1]

    def plan_slots(self) -> list[slot.Plan]:
        servers = self._all(SERVERS, "servers")
        server = self._range_server(servers)
        statuses = {server["id"]: self._setup_status(server)} if server else {}
        digest = rangehost.digest(self._bundle())
        return [self.in_slot(number)._plan(servers, digest, statuses) for number in range(1, self.slots + 1)]

    def ensure_slot(self, renew: bool = True) -> slot.Plan:
        with _booting:
            plan = self.plan_slot()
            if plan.blocked:
                raise Drifted("; ".join(plan.blocked))
            if plan.stale and renew:
                self._take_down_range_host()
                plan = self.plan_slot()
            if plan.boot:
                self._boot_range_host()
                plan = self.plan_slot()
        self._shape = None
        return plan

    def _take_down_range_host(self) -> list[tuple[str, str]]:
        servers = self._all(SERVERS, "servers")
        server = self._range_server(servers)
        steps = []
        if server is not None:
            self.get(self._call(DELETE_SERVER, server=server["id"]))
            steps.append(("server", server["id"]))
            self._until_gone({server["id"]})
            _set_up.discard(server["id"])
        name = self._port_name()
        for port in self._all(PROJECT_PORTS, "ports"):
            if port.get("name") == name and _detached(port):
                self.get(self._call(DELETE_PORT, port=port["id"]))
                steps.append(("port", port["id"]))
        self._shape = None
        return steps

    def _until_gone(self, servers: set[str]) -> None:
        deadline = time.monotonic() + GONE_WAIT
        while servers & {server["id"] for server in self._all(SERVERS, "servers")}:
            if time.monotonic() > deadline:
                raise Drifted(f"Nova did not delete {', '.join(sorted(servers))} within {GONE_WAIT}s")
            time.sleep(GONE_POLL)

    def _port_name(self) -> str:
        return f"{self.range_host}.{fabric.MANAGEMENT}"

    def _boot_range_host(self) -> None:
        networks, _, _, groups = self._fabric_standing()
        management = fabric.bound(self.declared, networks).get(fabric.MANAGEMENT)
        named = {group["name"]: group["id"] for group in groups}
        missing = [name for name in (fabric.MANAGEMENT_GROUP, fabric.EGRESS_GROUP) if name not in named]
        if management is None or missing:
            raise Drifted(f"the fabric has no {fabric.MANAGEMENT} network or no security group "
                          f"{', '.join(missing) or '-'}; build the fabric first")
        for port in self._all(PORTS, "ports", network=management["id"]):
            if port.get("name") == self._port_name() and _detached(port):
                self.get(self._call(DELETE_PORT, port=port["id"]))
        port = self.get(self._call(CREATE_PORT), {"port": {
            "network_id": management["id"], "name": self._port_name(),
            "security_groups": [named[fabric.MANAGEMENT_GROUP]],
        }})["port"]
        files = self._bundle()
        server = {
            "name": self.range_host,
            "imageRef": self._base_image(),
            "flavorRef": self._flavor(self.build.flavor),
            "networks": [{"port": port["id"]}, {"uuid": self.build.network}],
            "security_groups": [{"name": fabric.EGRESS_GROUP}],
            "config_drive": True, "key_name": fabric.KEYPAIR,
            "user_data": rangehost.user_data(files),
            "metadata": {slot.HOST: self.range_host, slot.TAG: self.build.image_tag,
                         slot.BUNDLE: rangehost.digest(files)},
        }
        try:
            self.get(self._call(BOOT), {"server": self.build.placed(server)})
        except RangeUnavailable:
            self.get(self._call(DELETE_PORT, port=port["id"]))
            raise

    def _base_image(self) -> str:
        bases = [image for image in self.get(self._call(IMAGES, name=quote(self.build.base_image))).get("images") or []
                 if image.get("status") == "active"]
        if len(bases) != 1:
            raise RangeUnavailable(
                f"the range host boots {self.build.base_image!r} and the cloud has {len(bases)} active "
                f"images by that name; set {SETTINGS['base_image']} to one it has exactly once")
        return bases[0]["id"]

    def _flavor(self, name: str) -> str:
        flavor = next((
            entry["id"] for entry in self.get(self._call(FLAVORS)).get("flavors") or []
            if name and entry.get("name") == name
        ), None)
        if flavor is None:
            raise RangeUnavailable(
                f"the cloud has no flavor {name!r}; set {SETTINGS['flavor']} "
                f"(compute.flavors.range in cloud.yaml) to one it lists"
            )
        return flavor

    def teardown_slot(self) -> list[tuple[str, str]]:
        server = self._range_server(self._all(SERVERS, "servers"))
        if server is None:
            return []
        self._shape = None
        try:
            ran = self._shell()(rangehost.down(self._laid_out()), timeout=rangehost.UP_TIMEOUT)
        except RangeUnavailable:
            return []
        if not ran.ok:
            raise Drifted(f"{self.range_host} did not take slot {self.slot} down: {ran.output[-1000:]}")
        return [("project", self._laid_out().project)]

    def teardown_range_host(self) -> list[tuple[str, str]]:
        with _booting:
            return self._take_down_range_host()

    def rebuild_slot(self, kept: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
        self.describe()
        ran = self._shell()(rangehost.down(self._laid_out()), timeout=rangehost.UP_TIMEOUT)
        if not ran.ok:
            raise Drifted(f"{self.range_host} did not take slot {self.slot} down: {ran.output[-1000:]}")
        self._shape = None
        return []

    def reset_slot(self) -> list[tuple[str, str]]:
        return []

    def reset_in_place(self, rebuilt=()) -> list[tuple[str, tuple[str, ...]]]:
        self.describe()
        ran = self._shell()(rangehost.reset(self._laid_out()), timeout=rangehost.RESET_TIMEOUT)
        if not ran.ok:
            if "compose.yaml" in ran.output and "no such file" in ran.output.lower():
                return self.configure_slot()
            raise Drifted(f"{self.range_host} did not reset slot {self.slot} (exit {ran.exit_code}): "
                          f"{ran.output[-1000:]}")
        return [(self.range_host, (f"reset slot {self.slot}",)), *self._seeded()]

    def configure_rebuilt(self, hosts) -> list[tuple[str, tuple[str, ...]]]:
        return []

    def configure_slot(self) -> list[tuple[str, tuple[str, ...]]]:
        self._shape = None
        self.describe()
        laid = self._laid_out()
        collector = self.address(SCORER_ROLE)
        senders = {service: (self.declared.host(role), tag) for service, (role, tag) in COLLECTED.items()}
        files = rangehost.slot_files(Path(self.build.source), laid, self._wargames(), self.declared.origins,
                                     self.declared.default_origin,
                                     rangehost.forwarding(laid, collector, fabric.COLLECTOR_PORT, senders))
        packed = base64.b64encode(rangehost.archive(files)).decode()
        done = alongside([self.open_collector], [self.keep_time])
        ran = self._shell()(rangehost.up(laid), stdin=packed, timeout=rangehost.UP_TIMEOUT)
        if not ran.ok:
            raise Drifted(f"{self.range_host} did not bring slot {self.slot} up (exit {ran.exit_code}): "
                          f"{ran.output[-1000:]}")
        return [*done, (self.range_host, (f"runs slot {self.slot} as {laid.project}",
                                          f"logs to {collector}:{fabric.COLLECTOR_PORT}")), *self._seeded()]

    def _seeded(self) -> list[tuple[str, tuple[str, ...]]]:
        baseline = (Path(self.build.source) / rangehost.BASELINE_RULES).read_text()
        done = []
        for role in SENSOR_ROLES:
            if role not in self.declared.roles:
                continue
            entry = self.declared.hosts[self.declared.host(role)]
            try:
                suricata.seed(baseline, self.runner(role), entry.reload.split(), entry.rules)
            except suricata.RuleApplyError as exc:
                raise Drifted(f"slot {self.slot}'s {role} did not load the baseline rules: {exc}")
            done.append((self.declared.host(role), (f"loaded {entry.rules}",)))
        return done

    def keep_time(self) -> tuple[str, tuple[str, ...]]:
        server = self.address(SCORER_ROLE)
        ran = self._shell()(clock.command(server), stdin=clock.timesyncd(server),
                            timeout=clock.FIRST_ANSWER + 60)
        if not ran.ok:
            raise Drifted(f"{self.range_host} did not take {server} as its time source "
                          f"(exit {ran.exit_code}): {ran.output[-1000:]}")
        return self.range_host, (f"keeps time by {server}",)

    def open_collector(self) -> tuple[str, tuple[str, ...]]:
        senders = [self._address(self.range_host)]
        group = next(
            group for group in self._all(SECURITY_GROUPS, "security_groups")
            if group["name"] == fabric.REACH_GROUP
        )
        create, delete = fabric.hearing(group, senders)
        for rule in delete:
            self.get(self._call(DELETE_RULE, rule=rule))
        for rule in create:
            self.get(self._call(CREATE_RULE), {"security_group_rule": rule})
        return self.declared.host(SCORER_ROLE), tuple(f"hears {sender}" for sender in senders)

    def plan_leftovers(self) -> list[tuple[str, str, str]]:
        servers = self._all(SERVERS, "servers")
        found = [("server", server["id"], f"{server['name']}: a VM of the range before the range host")
                 for server in servers
                 if slot.host_of(server) and slot.host_of(server) != self.range_host]
        found += [("server", server["id"], f"{server['name']}: an image builder")
                  for server in servers if BUILDS in (server.get("metadata") or {})]
        networks, subnets, _, groups = self._fabric_standing()
        retired = {network["id"] for network in networks if fabric.retired(network)}
        carried = {network["id"] for network in networks if fabric.segment_of(network) and not fabric.retired(network)}
        found += [("port", port["id"], f"{port.get('name') or port['id']}: a port the VM range left")
                  for port in self._all(PROJECT_PORTS, "ports")
                  if port.get("network_id") in retired
                  or (port.get("network_id") in carried and _detached(port)
                      and port.get("name") != self._port_name())]
        found += [("subnet", subnet["id"], f"{subnet.get('name') or subnet['id']}: on a retired network")
                  for subnet in subnets if subnet["network_id"] in retired]
        found += [("network", network["id"], f"{network['name']}: carried a segment the slots carry now")
                  for network in networks if network["id"] in retired]
        found += [("group", group["id"], f"{group['name']}: a security group of the VM range")
                  for group in groups if group["name"] in fabric.RETIRED_GROUPS]
        found += [("image", image["id"], f"{image.get('name')}: a role image of the VM range")
                  for image in self._own_images() if slot.BUNDLE in image]
        return found

    def clean_leftovers(self) -> list[tuple[str, str]]:
        found = self.plan_leftovers()
        servers = {ident for kind, ident, _ in found if kind == "server"}
        for ident in sorted(servers):
            self.get(self._call(DELETE_SERVER, server=ident))
        if servers:
            self._until_gone(servers)
        found = self.plan_leftovers()
        order = ("port", "subnet", "network", "group", "image")
        removed = [(kind, ident) for kind in order for each, ident, _ in found if each == kind]
        for kind, ident in removed:
            try:
                self.get(self._call(DELETES[kind], **{kind: ident}))
            except EndpointGone:
                continue
        self._shape = None
        return [("server", ident) for ident in sorted(servers)] + removed

    def _own_images(self) -> list[dict]:
        found, marker = [], ""
        for _ in range(PAGE_LIMIT):
            page = self.get(self._call(OWN_IMAGES) + (f"&marker={quote(marker)}" if marker else ""))
            found += page.get("images") or []
            if not page.get("next") or not page.get("images"):
                return found
            marker = page["images"][-1]["id"]
        raise RangeUnavailable(f"Glance listed more than {PAGE_LIMIT} pages of this project's images")

    def _call(self, call: str, **binding) -> str:
        return call.format(**vars(self.cloud), **binding)

    def _all(self, call: str, key: str, **binding) -> list:
        page = self.get(call.format(**vars(self.cloud), **binding))
        found = list(page.get(key) or [])

        for _ in range(PAGE_LIMIT):
            href = next((
                link["href"] for link in page.get(f"{key}_links") or []
                if link.get("rel") == "next" and link.get("href")
            ), "")
            if not href:
                return found
            page = self.get(f"GET {href}")
            found += list(page.get(key) or [])

        raise RangeUnavailable(
            f"{key} came back in more than {PAGE_LIMIT} pages, each one "
            f"pointing at the next; the cloud is looping or the range is not "
            f"what this platform is for"
        )
