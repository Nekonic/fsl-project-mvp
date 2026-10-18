from __future__ import annotations

import hashlib
import ipaddress
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from functools import partial
from pathlib import Path
from urllib.parse import quote

import requests
from dataclasses import dataclass, field, replace

from range import cloud as configured
from range import clock, fabric, images, interfaces, opnsense, slot, waf, wargame_host
from range.declared import Declaration
from rules import suricata
from range.ports import (
    Drifted, Node, Ran, RangeUnavailable, Segment, Sensor, Shape, execute,
    reported, reporting,
)

TOKEN = "POST {keystone}/v3/auth/tokens"
NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags-any={tags}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"
BOOT = "POST {nova}/servers"
PROJECT_NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}"
PROJECT_SUBNETS = "GET {neutron}/v2.0/subnets?project_id={project}"
PORTS = "GET {neutron}/v2.0/ports?network_id={network}"
CREATE_NETWORK = "POST {neutron}/v2.0/networks"
TAG_NETWORK = "PUT {neutron}/v2.0/networks/{network}/tags"
CREATE_SUBNETS = "POST {neutron}/v2.0/subnets"
DELETE_SUBNET = "DELETE {neutron}/v2.0/subnets/{subnet}"
DELETE_NETWORK = "DELETE {neutron}/v2.0/networks/{network}"
KEYPAIRS = "GET {nova}/os-keypairs"
IMPORT_KEYPAIR = "POST {nova}/os-keypairs"
DELETE_KEYPAIR = "DELETE {nova}/os-keypairs/{keypair}"
IMAGES = "GET {glance}/v2/images?name={name}"
OWN_IMAGES = "GET {glance}/v2/images?owner={project}&visibility=private&limit=100"
CREATE_IMAGE = "POST {glance}/v2/images"
IMAGE_FILE = "{glance}/v2/images/{image}/file"
DELETE_IMAGE = "DELETE {glance}/v2/images/{image}"
FLAVORS = "GET {nova}/flavors"
FLAVOR = "GET {nova}/flavors/{flavor}"
LIMITS = "GET {nova}/limits"
ACTION = "POST {nova}/servers/{server}/action"
DELETE_SERVER = "DELETE {nova}/servers/{server}"
SECURITY_GROUPS = "GET {neutron}/v2.0/security-groups?project_id={project}"
CREATE_GROUP = "POST {neutron}/v2.0/security-groups"
CREATE_RULE = "POST {neutron}/v2.0/security-group-rules"
DELETE_GROUP = "DELETE {neutron}/v2.0/security-groups/{group}"
DELETE_RULE = "DELETE {neutron}/v2.0/security-group-rules/{rule}"
CREATE_PORT = "POST {neutron}/v2.0/ports"
UPDATE_PORT = "PUT {neutron}/v2.0/ports/{port}"
DELETE_PORT = "DELETE {neutron}/v2.0/ports/{port}"
ATTACH = "POST {nova}/servers/{server}/os-interface"

DELETES = {
    "subnet": DELETE_SUBNET, "network": DELETE_NETWORK, "keypair": DELETE_KEYPAIR,
    "group": DELETE_GROUP, "port": DELETE_PORT, "server": DELETE_SERVER,
}

FIXED = "OS-EXT-IPS:type"
LAUNCHED = "OS-SRV-USG:launched_at"
PAGE_LIMIT = 50

CONNECT_TIMEOUT = 10
SERVER_ALIVE_INTERVAL = 15
SERVER_ALIVE_COUNT_MAX = 3
NOVA_MICROVERSION = "2.1"
SUBJECT_TOKEN = "X-Subject-Token"
SEGMENT_TAG = "fsl.segment.id"
ATTACKER_ROLE = "attacker"
SCORER_ROLE = "scorer"
OWN_LISTED_TIMEOUT = 60
GATEWAY_ROLE = "gateway"
BUILD_GROUP = "fsl-build"
SENSOR_ROLE = "sensor"
EDGE_REBOOT = 900
EDGE_POLL = 3
EDGE_SETTLE_READS = 40
HOST_READS = 100
HOST_POLL = 3
RESET_IN_PLACE = (slot.EDGE_ROLE, wargame_host.ROLE)
DISK_TIMEOUT = 60
UPLOAD_TIMEOUT = 600
CHUNK = 1 << 20

SETTINGS = {
    "keystone": "FSL_OPENSTACK_KEYSTONE",
    "user": "FSL_OPENSTACK_USER",
    "domain": "FSL_OPENSTACK_DOMAIN",
    "password": "FSL_OPENSTACK_PASSWORD",
    "project": "FSL_OPENSTACK_PROJECT",
    "ssh_user": "FSL_OPENSTACK_SSH_USER",
    "ssh_key": "FSL_OPENSTACK_SSH_KEY",
    "region": "FSL_OPENSTACK_REGION",
    "interface": "FSL_OPENSTACK_INTERFACE",
    "source": "FSL_SOURCE",
    "base_image": "FSL_OPENSTACK_BASE_IMAGE",
    "flavor": "FSL_OPENSTACK_FLAVOR",
    "build_flavor": "FSL_OPENSTACK_BUILD_FLAVOR",
    "role_flavors": "FSL_OPENSTACK_ROLE_FLAVORS",
    "availability_zone": "FSL_OPENSTACK_AVAILABILITY_ZONE",
    "subnets": "FSL_OPENSTACK_SUBNETS",
    "mtu": "FSL_OPENSTACK_MTU",
    "opnsense": "FSL_OPNSENSE",
    "build_network": "FSL_OPENSTACK_BUILD_NETWORK",
    "platform": "FSL_OPENSTACK_PLATFORM",
    "image_tag": "FSL_IMAGE_TAG",
    "slots": "FSL_OPENSTACK_SLOTS",
    "sideloaded": "FSL_SIDELOADED",
}
ROOM = (("maxTotalInstances", "totalInstancesUsed", ""), ("maxTotalCores", "totalCoresUsed", "vcpus"),
        ("maxTotalRAMSize", "totalRAMUsed", "ram"))

_connected: dict[tuple, tuple["Cloud", object]] = {}

class EndpointGone(RangeUnavailable):
    pass

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
    build_flavor: str = "",
    role_flavors: str = "",
    availability_zone: str = "",
    subnets: str = "",
    mtu: str = "",
    opnsense: str = "",
    build_network: str = "",
    platform: str = "",
    image_tag: str = "",
    slots: str = "",
    sideloaded: str = "",
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
            build_flavor=build_flavor, role_flavors=configured.pairs(role_flavors),
            availability_zone=availability_zone, inside=configured.pairs(subnets),
            mtu=int(mtu or 0), opnsense=configured.opnsense_from(opnsense),
            network=build_network, platform=platform, image_tag=image_tag,
            slots=_count(slots or "1"),
            sideloaded=frozenset(name for name in sideloaded.split(",") if name),
        )
    except ValueError as error:
        raise RangeUnavailable(
            f"the cloud settings ({', '.join(SETTINGS[n] for n in ('role_flavors', 'subnets', 'mtu', 'opnsense', 'slots'))}) "
            f"do not parse: {error}; they come from cloud.yaml through the Heat stack"
        ) from error
    cloud, reader = _connected.get(known) or rediscover()
    return OpenStack(declared, cloud, get=reader, rediscover=rediscover, build=build)

def _count(text: str) -> int:
    count = int(text)
    if count < 1:
        raise ValueError(f"{SETTINGS['slots']} is {count}; a range has one slot or more")
    return count

def once_it_answers(step):
    for _ in range(HOST_READS - 1):
        try:
            return step()
        except RangeUnavailable:
            time.sleep(HOST_POLL)
    return step()

def alongside(*chains: list) -> list:
    def in_order(chain: list) -> list:
        return [once_it_answers(step) for step in chain]

    with ThreadPoolExecutor(max_workers=max(1, len(chains))) as pool:
        running = [pool.submit(in_order, chain) for chain in chains]
        wait(running)
    return [done for finished in running for done in finished.result()]

def forget() -> None:
    _connected.clear()

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

    def upload(url: str, disk: Path) -> None:
        def put(token: str):
            with open(disk, "rb") as content:
                return requests.put(url, data=content, timeout=UPLOAD_TIMEOUT, headers={
                    "X-Auth-Token": token, "Content-Type": "application/octet-stream"})
        try:
            answered = put(authenticate())
            if answered.status_code == 401:
                answered = put(authenticate())
        except requests.RequestException as exc:
            raise RangeUnavailable(f"could not upload {disk.name} to {url}: {exc}") from exc
        if not answered.ok:
            raise RangeUnavailable(
                f"PUT {url} answered {answered.status_code}: {answered.text.strip()[:200]}")

    send.upload = upload
    return send

def pull(url: str, into: Path, timeout: float = DISK_TIMEOUT) -> str:
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=timeout) as answered:
            if not answered.ok:
                raise RangeUnavailable(f"GET {url} answered {answered.status_code}")
            with open(into, "wb") as disk:
                for chunk in answered.iter_content(CHUNK):
                    disk.write(chunk)
                    digest.update(chunk)
    except requests.RequestException as exc:
        raise RangeUnavailable(f"could not pull the disk from {url}: {exc}") from exc
    return digest.hexdigest()

def _fixed_ipv4(server: dict) -> str:
    found = next((
        entry["addr"] for entries in (server.get("addresses") or {}).values() for entry in entries
        if entry.get(FIXED, "fixed") == "fixed" and entry.get("version", 4) == 4
    ), "")
    if not found:
        raise RangeUnavailable(f"builder {server.get('name', server['id'])} has no fixed IPv4 address to pull its disk from")
    return found

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

def _origin_subnet(origin, network: dict, allocated: list[dict]) -> dict:
    found = next((s for s in allocated if s.get("cidr") == origin.subnet), None)
    if found is None:
        raise RangeUnavailable(
            f"origin {origin.id!r} is declared on {origin.subnet} and network "
            f"{network.get('name') or network['id']} has no such subnet"
        )
    return found

def _refuse_undeclared(origins, bound: dict, allocated: dict) -> None:
    declared = {(origin.segment, origin.subnet) for origin in origins}
    for carrier in {origin.segment for origin in origins}:
        stray = [
            subnet.get("cidr", "") for subnet in allocated.get(carrier, [])
            if subnet.get("ip_version", 4) == 4 and (carrier, subnet.get("cidr")) not in declared
        ]
        if stray:
            raise RangeUnavailable(
                f"network {bound[carrier].get('name') or bound[carrier]['id']} "
                f"carries {stray}, which no origin declares; an address there "
                f"would be binned to no country"
            )

def _subnet_body(subnet: "fabric.Subnet", network_id: str) -> dict:
    body = {
        "network_id": network_id, "name": subnet.name, "cidr": subnet.cidr,
        "ip_version": 4, "enable_dhcp": subnet.dhcp,
    }
    if not subnet.gateway:
        body["gateway_ip"] = None
    return body

def _tidied(piped: subprocess.Popen, scratch: Path) -> None:
    piped.wait()
    shutil.rmtree(scratch, ignore_errors=True)

def _generations(servers: list[dict]) -> dict[str, str]:
    found = {}
    for server in servers:
        if not server.get("id"):
            continue
        booted = "".join(c for c in str(server.get(LAUNCHED) or "") if c.isdigit())
        generation = "-".join(filter(None, ("fsl", server["id"], booted)))
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
    build_flavor: str = ""
    role_flavors: dict = field(default_factory=dict)
    availability_zone: str = ""
    inside: dict = field(default_factory=dict)
    mtu: int = 0
    opnsense: configured.OPNsense | None = None
    network: str = ""
    platform: str = ""
    image_tag: str = ""
    slots: int = 1
    sideloaded: frozenset = frozenset()

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

    def _visible(self, servers: list[dict]) -> list[dict]:
        return [server for server in servers
                if not slot.in_slot(server) or slot.slot_of(server) == self.slot]

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
        origins = {origin.id: origin for origin in self.declared.origins}
        carriers = list(dict.fromkeys(
            origins[segment.id].segment if segment.id in origins else segment.id
            for segment in self.declared.segments
        ))
        wanted = ",".join(f"{SEGMENT_TAG}={carrier}" for carrier in carriers)
        bound = self._bind(self._all(NETWORKS, "networks", tags=wanted))
        servers = self._visible(self._all(SERVERS, "servers"))
        self._generations = _generations(servers)

        allocated = {}
        for carrier in carriers:
            network = bound.get(carrier)
            if network is None:
                raise RangeUnavailable(
                    f"the declaration names the segment {carrier!r} and no "
                    f"network of project {self.cloud.project!r} is tagged "
                    f"{SEGMENT_TAG}={carrier}"
                )
            allocated[carrier] = self._all(SUBNETS, "subnets", network=network["id"])
        _refuse_undeclared(origins.values(), bound, allocated)

        segments = []
        for declared in self.declared.segments:
            origin = origins.get(declared.id)
            carrier = origin.segment if origin else declared.id
            network = bound[carrier]
            bound_subnet = (
                _origin_subnet(origin, network, allocated[carrier]) if origin
                else _one_ipv4_subnet(declared.id, allocated[carrier])
            )
            segments.append(
                replace(
                    declared,
                    subnet=bound_subnet.get("cidr", ""),
                    network=network["id"],
                    gateway=bound_subnet.get("gateway_ip") or "",
                    nodes=self._nodes(network["name"], servers, bound_subnet.get("cidr", "")),
                )
            )

        return Shape(segments=tuple(segments), sensors=self._sensors(servers))

    def runner(self, role: str, segment_id: str = ""):
        host = self.declared.host(role)
        container = self._container(role, host)

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            address = self._address(role, host, segment_id)
            with tempfile.TemporaryDirectory() as scratch:
                said = Path(scratch) / "ssh.log"
                config = self._config(Path(scratch) / "ssh_config", address)
                command = self._ssh(address, stdin is not None, said, config,
                                    self._ssh_user(host))
                sent = reporting(argv)
                if container:
                    sent = wargame_host.inside(container, sent, stdin is not None)
                command.append(shlex.join(sent))
                done = execute(host, command, stdin, timeout)
                logged = said.read_text() if said.exists() else ""
                complaint = " ".join(filter(None, (
                    line.strip("@ ") for line in
                    f"{logged}\n{done.stderr or ''}".splitlines()
                )))

            ran = reported(done)
            if ran is None:
                raise RangeUnavailable(
                    f"{host} at {address} never reported the command "
                    f"finishing: "
                    + (complaint[:1000] or "the connection ended before it did")
                )
            return ran

        return run

    def interfaces(self, hosts=None) -> list[interfaces.Interface]:
        origins = {origin.id: origin.segment for origin in self.declared.origins}
        subnets = [(segment.subnet, origins.get(segment.id, segment.id)) for segment in self.describe().segments]
        found = []
        for host, entry in sorted(self.declared.hosts.items()):
            if hosts is not None and host not in hosts:
                continue
            role = next((role for role, named in sorted(self.declared.roles.items())
                         if named == host and not self._container(role, host)), "")
            if not role:
                continue
            try:
                run = self.runner(role)
                own = run(["sh", "-c", interfaces.LISTED], timeout=30).output
                if entry.wargames:
                    bridges, inside = interfaces.containers(
                        own, run(["sudo", "sh", "-c", interfaces.CONTAINERS], timeout=60).output)
                    for service, said in sorted(inside.items()):
                        found += interfaces.placed(service, said, bridges)
                    subnets_here = subnets + bridges
                else:
                    subnets_here = subnets
                found += interfaces.placed(host, own, subnets_here)
            except RangeUnavailable:
                continue
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

    def _container(self, role: str, host: str) -> str:
        entry = self.declared.hosts.get(host)
        return self.declared.compose.get(role, "") if entry and entry.wargames else ""

    def _ssh_user(self, host: str) -> str:
        entry = self.declared.hosts.get(host)
        return entry.ssh_user if entry and entry.ssh_user else self.cloud.ssh_user

    def _ssh(self, address: str, reads_input: bool, log: Path, config: Path,
             ssh_user: str) -> list[str]:
        command = ["ssh", "-F", str(config)]
        if not reads_input:
            command.append("-n")
        return command + [
            "-i", self.cloud.ssh_key,
            "-E", str(log),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "LogLevel=ERROR",
            f"{ssh_user}@{address}",
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
                    f"asked to start {image!r} on {segment_id!r}. Nova has no "
                    f"call that boots a host, hands back its output and "
                    f"deletes it, so a tool runs on the attacker this range "
                    f"already has - {attacker!r} - and no other image"
                )
            self._address(ATTACKER_ROLE, attacker, segment_id)
            return self.runner(ATTACKER_ROLE)(argv, timeout=timeout)

        return launch

    def users_box(self, segment_ids: list[str], image: str):
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")
        if image != attacker:
            raise RangeUnavailable(
                f"asked to run customers from {image!r}; on OpenStack they run on the attacker "
                f"this range already has - {attacker!r} - which stands on every origin"
            )
        return self.runner(ATTACKER_ROLE)

    def opened(self, role: str, argv: list[str]) -> socket.socket:
        host = self.declared.host(role)
        address = self._address(role, host, "")
        scratch = Path(tempfile.mkdtemp())
        config = self._config(scratch / "ssh_config", address)
        command = self._ssh(address, True, scratch / "ssh.log", config, self._ssh_user(host))
        ours, theirs = socket.socketpair()
        try:
            piped = subprocess.Popen(command + [shlex.join(argv)], stdin=theirs, stdout=theirs,
                                     stderr=subprocess.DEVNULL)
        except OSError as exc:
            ours.close()
            shutil.rmtree(scratch, ignore_errors=True)
            raise RangeUnavailable(f"could not reach {host}: {exc}") from exc
        finally:
            theirs.close()
        threading.Thread(target=_tidied, args=(piped, scratch), daemon=True).start()
        return ours

    def _bind(self, networks: list[dict]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for network in networks:
            for tag in network.get("tags") or []:
                mark, _, segment_id = tag.partition("=")
                if mark != SEGMENT_TAG or not segment_id:
                    continue
                if fabric.slot_of(network) != fabric.owner(segment_id, self.slot):
                    continue
                if segment_id in found:
                    raise RangeUnavailable(
                        f"{found[segment_id]['id']} and {network['id']} both "
                        f"carry {SEGMENT_TAG}={segment_id!r}, so nothing says "
                        f"which of them the segment is"
                    )
                found[segment_id] = network
        return found

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

    def _sensors(self, servers: list[dict]) -> tuple[Sensor, ...]:
        standing = {slot.known_as(server) for server in servers}
        return tuple(
            Sensor(name=name, watches=host)
            for name, host in self.declared.watching()
            if name in standing and host in standing
        )

    def _address(self, role: str, host: str, segment_id: str) -> str:
        segments = sorted(self.describe().segments, key=lambda s: s.id != fabric.MANAGEMENT)
        for segment in segments:
            if segment_id and segment.id != segment_id:
                continue
            for node in segment.nodes:
                if node.name == host:
                    return node.address
        raise RangeUnavailable(
            f"the host filling {role!r} ({host}) stands on no segment this "
            f"platform can address"
            + (f", and {segment_id!r} in particular" if segment_id else "")
        )

    def plan_fabric(self) -> fabric.Plan:
        networks, subnets, keypairs, groups = self._fabric_standing()
        return fabric.plan(self.declared, networks, subnets, keypairs, self._public_key(),
                           groups, self._reached(networks), self.build.inside, self.slots)

    def ensure_fabric(self) -> fabric.Plan:
        public_key = self._public_key(make=True)
        networks, subnets, keypairs, groups = self._fabric_standing()
        plan = fabric.plan(self.declared, networks, subnets, keypairs, public_key,
                           groups, self._reached(networks), self.build.inside, self.slots)
        if plan.drifted:
            raise Drifted("; ".join(plan.drifted))
        carriers = {
            fabric.carrier(segment, number): network["id"]
            for number in range(1, self.slots + 1)
            for segment, network in fabric.bound(self.declared, networks, number).items()
        }
        wanted = {fabric.carrier(subnet.segment, subnet.slot): (subnet.segment, subnet.slot)
                  for number in range(1, self.slots + 1)
                  for subnet in fabric.wanted(self.declared, self.build.inside, number)}
        carriers.update({carrier: self._make_network(*wanted[carrier]) for carrier in plan.networks})
        if plan.subnets:
            self.get(self._call(CREATE_SUBNETS), {"subnets": [
                _subnet_body(subnet, carriers[subnet.carrier]) for subnet in plan.subnets
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
            if name == fabric.RANGE_GROUP:
                self.get(self._call(CREATE_RULE), {"security_group_rule": {
                    "security_group_id": named[name], "direction": "ingress",
                    "ethertype": "IPv4",
                }})
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
        port = self.get(self._call(CREATE_PORT), {"port": {
            "network_id": network, "name": f"{fabric.KEYPAIR}.{fabric.MANAGEMENT}",
            "security_groups": [group],
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
        owned = {network["id"]: network for number in range(1, self.slots + 1)
                 for network in fabric.bound(self.declared, networks, number).values()}
        for network in owned.values():
            servers = [
                port for port in self._all(PORTS, "ports", network=network["id"])
                if str(port.get("device_owner") or "").startswith("compute:")
            ]
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

    def _make_network(self, segment: str, number: int = 1) -> str:
        created = self.get(self._call(CREATE_NETWORK), {
            "network": {"name": fabric.network_name(segment, number)}
        })["network"]
        try:
            self.get(self._call(TAG_NETWORK, network=created["id"]), {
                "tags": fabric.network_tags(segment, number)
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

    def plan_images(self) -> images.Plan:
        return self._image_plan(self._bundles())

    def ensure_images(self) -> images.Plan:
        bundles = self._bundles()
        plan = self._image_plan(bundles)
        made = {bundle.host: bundle for bundle in bundles}
        missing = [found for found in plan.images
                   if found.state == "missing" and found.host in made]
        room = self._builder_room() if missing else 0
        if missing and room < 1 and not any(found.builder for found in plan.images):
            raise RangeUnavailable(
                f"{', '.join(found.host for found in missing)} need a builder and the project's "
                f"quota has no room for one ({self.build.build_flavor}); take a slot down "
                f"(DELETE /api/range/slot/?slot={self.slots}) or raise the quota, then build again"
            )
        for found in missing[:max(0, room)]:
            server = {
                **self._builder_base(self.build.base_image),
                "name": images.BUILDER + found.host,
                "user_data": images.user_data(made[found.host]),
                "metadata": {images.BUILDS: found.host, images.BUNDLE: found.bundle},
            }
            if made[found.host].uploads:
                self._build_group()
                server["security_groups"] = [{"name": BUILD_GROUP}]
            self.get(self._call(BOOT), {"server": self.build.placed(server)})
        for found in plan.images:
            if found.state == "built" and made[found.host].uploads:
                self._take_disk(made[found.host], found)
            elif found.state == "built":
                self.get(self._call(ACTION, server=found.builder), {"os-stop": None})
            elif found.state == "stopped":
                self.get(self._call(ACTION, server=found.builder), {"createImage": {
                    "name": found.host, "metadata": {images.BUNDLE: found.bundle},
                }})
            elif found.state == "ready" and found.builder:
                self.get(self._call(DELETE_SERVER, server=found.builder))
        return self._image_plan(bundles)

    def _builder_room(self) -> int:
        absolute = (self.get(self._call(LIMITS)).get("limits") or {}).get("absolute") or {}
        flavor = self.get(self._call(
            FLAVOR, flavor=self._flavor(self.build.build_flavor, "build_flavor"))).get("flavor") or {}
        rooms = [
            (absolute[most] - absolute.get(used, 0)) // max(1, int(flavor.get(each) or 1) if each else 1)
            for most, used, each in ROOM
            if isinstance(absolute.get(most), int) and absolute[most] >= 0
        ]
        return min(rooms, default=len(self.declared.hosts))

    def _platform_address(self, why: str) -> str:
        if not self.build.platform:
            raise RangeUnavailable(f"{why}, so the platform needs its own server id; set {SETTINGS['platform']}")
        own = next((port for port in self._all(PORTS, "ports", network=self.build.network)
                    if port.get("device_id") == self.build.platform and port.get("fixed_ips")), None)
        if own is None:
            raise RangeUnavailable(f"the platform has no port on the build network {self.build.network}")
        return own["fixed_ips"][0]["ip_address"]

    def _build_group(self) -> str:
        address = self._platform_address("a builder that serves its disk lets in only the platform")
        wanted = {"direction": "ingress", "ethertype": "IPv4", "protocol": "tcp",
                  "port_range_min": images.SERVE_PORT, "port_range_max": images.SERVE_PORT,
                  "remote_ip_prefix": f"{address}/32"}
        group = next((g for g in self._all(SECURITY_GROUPS, "security_groups")
                      if g["name"] == BUILD_GROUP), None)
        if group is None:
            group = self.get(self._call(CREATE_GROUP), {"security_group": {"name": BUILD_GROUP}})["security_group"]
        ingress = [rule for rule in group.get("security_group_rules") or []
                   if rule.get("direction") == "ingress"]
        held = [rule for rule in ingress if all(rule.get(key) == value for key, value in wanted.items())]
        for rule in ingress:
            if rule not in held:
                self.get(self._call(DELETE_RULE, rule=rule["id"]))
        if not held:
            self.get(self._call(CREATE_RULE), {"security_group_rule": {
                **wanted, "security_group_id": group["id"]}})
        return group["id"]

    def _take_disk(self, bundle: images.Bundle, found: images.Image) -> None:
        upload = getattr(self.get, "upload", None)
        if upload is None:
            raise RangeUnavailable("this connection cannot upload an image to Glance")
        builder = next(s for s in self._all(SERVERS, "servers") if s["id"] == found.builder)
        wanted = images.served_sha256(self._console(found.builder), bundle.digest)
        if not wanted:
            raise RangeUnavailable(f"{builder['name']} said it finished and named no sha256 of its disk")
        source = f"http://{_fixed_ipv4(builder)}:{images.SERVE_PORT}/{images.DISK}"
        with tempfile.TemporaryDirectory() as scratch:
            disk = Path(scratch) / images.DISK
            got = pull(source, disk)
            if got != wanted:
                raise RangeUnavailable(
                    f"the disk pulled from {source} has sha256 {got} and {builder['name']} "
                    f"said {wanted}, so nothing went to Glance")
            image = found.image or self.get(
                self._call(CREATE_IMAGE), images.record(bundle, opnsense.IMAGE_PROPERTIES))["id"]
            upload(self._call(IMAGE_FILE, image=image), disk)

    def clean_images(self) -> list[tuple[str, str]]:
        removed = images.removable(self.plan_images())
        for kind, ident in removed:
            gone = DELETE_IMAGE if kind == "image" else DELETE_SERVER
            self.get(self._call(gone, image=ident, server=ident))
        return removed

    def _bundles(self) -> tuple[images.Bundle, ...]:
        return tuple(
            self._bundle(host, entry)
            for host, entry in self.declared.hosts.items()
            if entry.setup
        )

    def _bundle(self, host: str, entry) -> images.Bundle:
        source = Path(self.build.source)
        if entry.wargames:
            return images.bundle(source, host, entry.setup, entry.files, generated=wargame_host.generated(
                source, host, entry.wargames, entry.publish, self.build.image_tag, self.build.mtu,
                loaded=self._loaded(entry.wargames)))
        if not entry.uploads:
            return images.bundle(source, host, entry.setup, entry.files)
        if entry.uploads != opnsense.UPLOADS:
            raise RangeUnavailable(f"{host} uploads {entry.uploads!r}, which no builder makes")
        if self.build.opnsense is None or not self.build.mtu:
            raise RangeUnavailable(
                f"the {host} image is built from the OPNsense release and the tenant MTU; "
                f"set {SETTINGS['opnsense']} and {SETTINGS['mtu']} (opnsense and network.mtu in cloud.yaml)"
            )
        key = self._public_key()
        if not key:
            raise RangeUnavailable(f"the {host} image trusts the platform's key, which the fabric makes; build the fabric first")
        generated = opnsense.image_bundle(
            (source / opnsense.CONFIG).read_text(), self.build.opnsense, self.build.mtu, key)
        return images.bundle(source, host, entry.setup, entry.files, generated=generated,
                             image=self.build.opnsense.image, uploads=True)

    def sideloaded_image(self, name: str) -> str:
        wargames = [wargame for entry in self.declared.hosts.values() for wargame in entry.wargames]
        return wargame_host.sideloaded_images(
            self.build.source, wargames, self.build.image_tag, self.build.sideloaded).get(name, "")

    def _loaded(self, wargames) -> tuple[tuple[str, str, str], ...]:
        found = wargame_host.sideloaded_images(
            self.build.source, wargames, self.build.image_tag, self.build.sideloaded)
        if not found:
            return ()
        address = self._platform_address("the wargame host's builder fetches sideloaded images from the platform")
        return tuple(
            (image, wargame_host.local_image_id(image), wargame_host.SERVED_AT.format(address=address, name=name))
            for name, image in sorted(found.items()))

    def _prebuilt(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (host, entry.image)
            for host, entry in self.declared.hosts.items()
            if entry.image
        )

    def _image_plan(self, bundles) -> images.Plan:
        prebuilt = self._prebuilt()
        names = {bundle.name for bundle in bundles} | {image for _, image in prebuilt}
        found = [
            image for name in names
            for image in self.get(self._call(IMAGES, name=quote(name))).get("images") or []
        ]
        if any(bundle.uploads for bundle in bundles):
            found += [image for image in self._own_images()
                      if image.get("name") not in names
                      and str(image.get("name", "")).startswith(configured.OPNSENSE_FAMILY)]
        digests = {bundle.digest for bundle in bundles}
        servers = self._all(SERVERS, "servers")
        builders = [server for server in servers if images.BUILDS in (server.get("metadata") or {})]
        in_use = {(server.get("image") or {}).get("id") for server in servers
                  if isinstance(server.get("image"), dict)}
        consoles = {
            server["id"]: self._console(server["id"])
            for server in builders
            if server.get("status") == "ACTIVE"
            and server["metadata"].get(images.BUNDLE) in digests
        }
        return images.plan(bundles, found, builders, consoles, prebuilt=prebuilt,
                           families=(configured.OPNSENSE_FAMILY,), in_use=frozenset(in_use))

    def _own_images(self) -> list[dict]:
        found, marker = [], ""
        for _ in range(PAGE_LIMIT):
            page = self.get(self._call(OWN_IMAGES) + (f"&marker={quote(marker)}" if marker else ""))
            found += page.get("images") or []
            if not page.get("next") or not page.get("images"):
                return found
            marker = page["images"][-1]["id"]
        raise RangeUnavailable(f"Glance listed more than {PAGE_LIMIT} pages of this project's images")

    def _console(self, server: str) -> str:
        try:
            said = self.get(self._call(ACTION, server=server), {"os-getConsoleOutput": {}})
        except EndpointGone:
            return ""
        return said.get("output") or ""

    def _builder_base(self, base_image: str) -> dict:
        if not self.build.network:
            raise RangeUnavailable(
                f"an image is built on a server that downloads its packages, so "
                f"it needs a network that reaches the Internet; set "
                f"{SETTINGS['build_network']} to one"
            )
        bases = [
            image for image in self.get(
                self._call(IMAGES, name=quote(base_image))
            ).get("images") or []
            if image.get("status") == "active"
        ]
        if len(bases) != 1:
            raise RangeUnavailable(
                f"images are built on {base_image!r} and the cloud has "
                f"{len(bases)} active images by that name; set "
                f"{SETTINGS['base_image']} to one it has exactly once"
            )
        return {
            "imageRef": bases[0]["id"],
            "flavorRef": self._flavor(self.build.build_flavor, "build_flavor"),
            "networks": [{"uuid": self.build.network}], "config_drive": True,
        }

    def _flavor(self, name: str, setting: str) -> str:
        flavor = next((
            entry["id"] for entry in self.get(self._call(FLAVORS)).get("flavors") or []
            if name and entry.get("name") == name
        ), None)
        if flavor is None:
            raise RangeUnavailable(
                f"the cloud has no flavor {name!r}; set {SETTINGS[setting]} "
                f"(compute.flavors in cloud.yaml) to one it lists"
            )
        return flavor

    def _host_flavor(self, host: str) -> str:
        roles = [role for role, filled in self.declared.roles.items() if filled == host]
        named = next((self.build.role_flavors[role] for role in roles
                      if role in self.build.role_flavors), "")
        return self._flavor(named or self.build.flavor, "role_flavors" if named else "flavor")

    def plan_slot(self) -> slot.Plan:
        return self._slot()[0]

    def ensure_slot(self) -> slot.Plan:
        plan, bound, subnets, ports, groups, ready = self._slot()
        if plan.blocked:
            raise Drifted("; ".join(plan.blocked))
        named_groups = self._slot_groups(groups)
        self._fence_management(bound, ports, named_groups[fabric.MANAGEMENT_GROUP])
        if not plan.boot:
            return plan
        edge = slot.edge_of(self.declared)
        own = self._port_name
        for port in plan.ports:
            body = {"network_id": bound[port.segment]["id"], "name": port.name,
                    "security_groups": [named_groups[fabric.group_of(port.segment)]]}
            if port.fixed_ips:
                body["fixed_ips"] = [
                    {"subnet_id": subnet, "ip_address": address} for subnet, address in port.fixed_ips
                ]
            if port.host == edge and port.segment != fabric.MANAGEMENT:
                body["allowed_address_pairs"] = [{"ip_address": "0.0.0.0/0"}]
            ports.append(self.get(self._call(CREATE_PORT), {"port": body})["port"])
        named = {port["name"]: port for port in ports if port.get("name")}
        names = {
            named[own(host, slot.NAMED_ON)]["fixed_ips"][0]["ip_address"]: list(entry.names)
            for host, entry in self.declared.hosts.items()
            if entry.names and own(host, slot.NAMED_ON) in named
        }
        prefixes = {subnet["id"]: subnet["cidr"].split("/")[1] for subnet in subnets}
        outside = {origin.segment for origin in self.declared.origins}
        for host in plan.boot:
            entry = self.declared.hosts[host]
            facing = [named[own(host, s)] for s in entry.segments if s in outside]
            server = {
                "name": slot.named(host, self.slot), "imageRef": ready[host],
                "flavorRef": self._host_flavor(host),
                "networks": [{"port": named[own(host, s)]["id"]} for s in entry.segments],
                "config_drive": True, "key_name": fabric.KEYPAIR,
                "metadata": {slot.HOST: host, **({slot.SLOT: str(self.slot)} if self.slot > 1 else {})},
            }
            if not entry.image and not entry.uploads:
                server["user_data"] = slot.user_data(
                    names,
                    mac=facing[0]["mac_address"] if facing else "",
                    addresses=tuple(
                        f"{fixed['ip_address']}/{prefixes[fixed['subnet_id']]}"
                        for port in facing for fixed in port["fixed_ips"]
                    ),
                )
            self.get(self._call(BOOT), {"server": self.build.placed(server)})
        self._shape = None
        return self._slot()[0]

    def _port_name(self, host: str, segment: str) -> str:
        return slot.port_name(slot.named(host, self.slot), segment)

    @staticmethod
    def _slot_groups(groups: list) -> dict[str, str]:
        named = {g["name"]: g["id"] for g in groups}
        missing = [name for name in (fabric.RANGE_GROUP, fabric.MANAGEMENT_GROUP) if name not in named]
        if missing:
            raise Drifted(f"the fabric has no security group {', '.join(missing)}; build the fabric first")
        return named

    def _fence_management(self, bound: dict, ports: list, fenced: str) -> None:
        names = {self._port_name(host, fabric.MANAGEMENT) for host in self.declared.hosts}
        for port in ports:
            if (port["network_id"] == bound[fabric.MANAGEMENT]["id"] and port.get("name") in names
                    and list(port.get("security_groups") or []) != [fenced]):
                self.get(self._call(UPDATE_PORT, port=port["id"]),
                         {"port": {"security_groups": [fenced]}})
                port["security_groups"] = [fenced]

    def teardown_slot(self) -> list[tuple[str, str]]:
        hosts = self.declared.hosts
        bound = fabric.bound(self.declared, self._all(PROJECT_NETWORKS, "networks"), self.slot)
        made = {self._port_name(host, s) for host, entry in hosts.items() for s in entry.segments}
        steps = [
            ("server", server["id"]) for server in self._all(SERVERS, "servers")
            if (server.get("metadata") or {}).get(slot.HOST) in hosts
            and slot.slot_of(server) == self.slot
        ] + [
            ("port", port["id"])
            for network in bound.values()
            for port in self._all(PORTS, "ports", network=network["id"])
            if port.get("name") in made
        ]
        for kind, ident in steps:
            self.get(self._call(DELETES[kind], **{kind: ident}))
        self._shape = None
        return steps

    def rebuild_slot(self, kept: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
        plan, _bound, _subnets, _ports, _groups, ready = self._slot()
        if plan.blocked:
            raise Drifted("; ".join(plan.blocked))
        if plan.boot:
            raise Drifted(
                f"the slot is not fully standing, so there is nothing to reset "
                f"for {', '.join(plan.boot)}; provision it first"
            )
        rebuilding = [(host, server) for host, server, _status in plan.standing if host not in kept]
        missing = [host for host, _server in rebuilding if host not in ready]
        if missing:
            raise Drifted(
                f"image {', '.join(missing)} is not ready, so rebuilding would "
                f"wipe some VMs and leave others; make the images ready first"
            )
        for host, server in rebuilding:
            self.get(self._call(ACTION, server=server), {"rebuild": {"imageRef": ready[host]}})
        self._shape = None
        return rebuilding

    def reset_slot(self) -> list[tuple[str, str]]:
        return self.rebuild_slot(kept=self.reset_in_place_hosts())

    def reset_in_place_hosts(self) -> frozenset[str]:
        return frozenset(self.declared.roles[role] for role in RESET_IN_PLACE
                         if role in self.declared.roles)

    def configure_slot(self) -> list[tuple[str, tuple[str, ...]]]:
        self.describe()
        first = (slot.edge_of(self.declared), self.declared.host(GATEWAY_ROLE))
        return alongside(*self._chains([*first, *self.declared.hosts]), [self.open_collector])

    def reset_in_place(self) -> list[tuple[str, tuple[str, ...]]]:
        self.describe()
        hosts = self.reset_in_place_hosts()
        edge = [self.reset_edge] if slot.edge_of(self.declared) in hosts else []
        wargames = ([self.clear_wargames, *self._wargame_chain()]
                    if wargame_host.ROLE in self.declared.roles else [])
        return alongside(edge, [self.open_collector], wargames)

    def configure_rebuilt(self, hosts) -> list[tuple[str, tuple[str, ...]]]:
        self._shape = None
        self.describe()
        return alongside(*self._chains(hosts))

    def _chains(self, hosts) -> list[list]:
        edge = slot.edge_of(self.declared)
        chains = {host: [partial(self.keep_time, host)]
                  for host in self.declared.hosts if host != edge and self._own_role(host)}
        chains[edge] = [self.configure_edge]
        gateway = self.declared.host(GATEWAY_ROLE)
        chains[gateway] = [*(chains.get(gateway, []) if gateway != edge else []), self.configure_waf]
        if wargame_host.ROLE in self.declared.roles:
            chains[self.declared.host(wargame_host.ROLE)] = self._wargame_chain()
        return [chains[host] for host in dict.fromkeys(hosts) if host in chains]

    def _own_role(self, host: str) -> str:
        return next((role for role, filled in sorted(self.declared.roles.items())
                     if filled == host and not self._container(role, host)), "")

    def keep_time(self, host: str) -> tuple[str, tuple[str, ...]]:
        role = self._own_role(host)
        server = self.address(SCORER_ROLE)
        ran = self.runner(role)(clock.command(server), stdin=clock.timesyncd(server),
                                timeout=clock.FIRST_ANSWER + 60)
        if not ran.ok:
            raise Drifted(f"{host} did not take {server} as its time source "
                          f"(exit {ran.exit_code}): {ran.output[-1000:]}")
        return host, (f"keeps time by {server}",)

    def _wargame_chain(self) -> list:
        chain = ([partial(self.keep_time, self.declared.host(wargame_host.ROLE)), self.start_wargames]
                 if wargame_host.ROLE in self.declared.roles else [])
        chain += [partial(self.start_sensor, role, host) for role, host in self._hosted_sensors()]
        chain += [partial(self.forward_logs, host)
                  for host, entry in sorted(self.declared.hosts.items())
                  if entry.logs and host in self.declared.roles.values()]
        return chain

    def clear_wargames(self) -> tuple[str, tuple[str, ...]]:
        host = self.declared.host(wargame_host.ROLE)
        entry = self.declared.hosts.get(host)
        if entry is None or not entry.wargames:
            raise Drifted(f"{host} fills {wargame_host.ROLE!r} and the declaration gives it no wargame to run")
        sensed = any(filled == host for _, filled in self._hosted_sensors())
        logs = tuple(path for _, path in sorted(entry.logs.items()))
        ran = self.runner(wargame_host.ROLE)(
            wargame_host.cleared(entry.wargames, logs, sensed), timeout=wargame_host.UP_TIMEOUT,
        )
        if not ran.ok:
            raise Drifted(f"{host} did not clear its wargames (exit {ran.exit_code}): {ran.output[-1000:]}")
        return host, tuple(f"cleared {wargame}" for wargame in entry.wargames) + (
            ("cleared its sensor and its log",) if sensed else ())

    def _hosted_sensors(self) -> list[tuple[str, str]]:
        return [
            (role, self.declared.host(role)) for role in sorted(self.declared.watches)
            if self._container(role, self.declared.host(role))
        ]

    def start_sensor(self, role: str, host: str) -> tuple[str, tuple[str, ...]]:
        address = self._address(role, host, slot.NAMED_ON)
        ran = self.runner(wargame_host.ROLE)(
            wargame_host.sensor_up(address),
            stdin=(Path(self.build.source) / wargame_host.SENSOR_CONFIG_SOURCE).read_text(),
            timeout=wargame_host.UP_TIMEOUT)
        if not ran.ok:
            raise Drifted(f"{host} did not start its sensor on {address} (exit {ran.exit_code}): "
                          f"{ran.output[-1000:]}")
        entry = self.declared.hosts[host]
        if not entry.rules or not entry.reload:
            raise Drifted(f"{host} runs a sensor and the declaration names no rule file and reload for it")
        try:
            suricata.seed((Path(self.build.source) / wargame_host.BASELINE_RULES).read_text(),
                          self.runner(role), entry.reload.split(), entry.rules)
        except suricata.RuleApplyError as exc:
            raise Drifted(f"{host} did not load the baseline rules into its sensor: {exc}")
        return host, (f"senses {slot.NAMED_ON} at {address}", f"loaded {entry.rules}")

    def forward_logs(self, host: str) -> tuple[str, tuple[str, ...]]:
        role = self._own_role(host)
        collector = self._collector()
        for tag, path in sorted(self.declared.hosts[host].logs.items()):
            ran = self.runner(role)(
                waf.command(tag), stdin=waf.forwarding(path, collector, fabric.COLLECTOR_PORT, tag),
                timeout=120,
            )
            if not ran.ok:
                raise Drifted(f"{host} did not take its {tag} log forwarding: {ran.output[-1000:]}")
        return host, tuple(f"logs {path} to {collector}:{fabric.COLLECTOR_PORT}"
                           for _, path in sorted(self.declared.hosts[host].logs.items()))

    def address(self, role: str) -> str:
        return self._address(role, self.declared.host(role), fabric.MANAGEMENT)

    def _collector(self) -> str:
        return self.address(SCORER_ROLE)

    def _edge_wanted(self) -> tuple[dict, tuple[str, int], str, str, str]:
        source = Path(self.build.source)
        collector = (self._collector(), fabric.COLLECTOR_PORT)
        wanted = opnsense.settings(self.describe().segments, collector, self.build.inside,
                                   self.build.mtu, self._public_key(),
                                   management=self.address(slot.EDGE_ROLE),
                                   front=self._address(GATEWAY_ROLE, self.declared.host(GATEWAY_ROLE),
                                                       slot.NAMED_ON),
                                   hostname=fabric.suffixed(opnsense.HOSTNAME, self.slot)
                                   if self.slot > 1 else "",
                                   clock=self.address(SCORER_ROLE))
        return (wanted, collector, opnsense.render((source / opnsense.CONFIG).read_text(), wanted),
                (source / opnsense.INCLUDE).read_text(), (source / opnsense.RULES).read_text())

    @staticmethod
    def _edge_expects(wanted: dict) -> list[str]:
        return [gateway["address"] for gateway in [wanted["wan"], *wanted["aliases"]]]

    def reset_edge(self) -> tuple[str, tuple[str, ...]]:
        wanted, collector, config, include, rules = self._edge_wanted()
        edge = slot.edge_of(self.declared)
        flushed = [segment.subnet for segment in self.describe().segments
                   if segment.id != fabric.MANAGEMENT and segment.subnet]
        ran = self.runner(slot.EDGE_ROLE)(
            opnsense.command(), stdin=opnsense.in_place(config, include, rules, flushed), timeout=180)
        drifted = opnsense.drifted(ran.output)
        why = (f"{', '.join(drifted)} drifted" if drifted
               else f"the in-place reset exited {ran.exit_code}")
        if ran.ok and opnsense.reset_done(ran.output):
            ran = self.runner(slot.EDGE_ROLE)(opnsense.verify(), timeout=60)
            if self._edge_holds_its_configuration(ran, self._edge_expects(wanted), collector):
                return edge, opnsense.reported(ran.output) + ("reset in place",)
            why = "it did not hold its configuration after the reset"
        host, reported = self.configure_edge()
        return host, reported + (f"reinstalled and rebooted: {why}",)

    def configure_edge(self) -> tuple[str, tuple[str, ...]]:
        source = Path(self.build.source)
        wanted, collector, config, include, rules = self._edge_wanted()
        edge = slot.edge_of(self.declared)
        staged = opnsense.playback(config, include, rules, (source / opnsense.SCRIPT).read_text())
        ran = self.runner(slot.EDGE_ROLE)(opnsense.command(), stdin=staged, timeout=120)
        before = opnsense.booted(ran.output)
        if not ran.ok or opnsense.REBOOTING not in ran.output or not before:
            raise Drifted(f"{edge} did not take its configuration (exit {ran.exit_code}): "
                          f"{ran.output[-1000:]}")
        ran = self._rebooted(edge, before)
        expected = self._edge_expects(wanted)
        ran = self._settled(ran, expected, collector)
        missing = [address for address in expected if address not in opnsense.held(ran.output)]
        reported = opnsense.reported(ran.output)
        sensing = opnsense.sensing(ran.output)
        logging = f"logs {collector[0]}:{collector[1]}" in reported
        wan_rule = opnsense.wan_rule_loaded(ran.output)
        if not ran.ok or missing or not sensing or not logging or not wan_rule:
            raise Drifted(
                f"{edge} came back with exit {ran.exit_code}, does not hold "
                f"{', '.join(missing) or 'nothing missing'}, its sensor is "
                f"{'running' if sensing else 'not running'}, it "
                f"{'logs' if logging else 'does not log'} to {collector[0]}:{collector[1]}, and "
                f"its wan pass rule is {'in pf' if wan_rule else 'not loaded into pf'}: "
                f"{ran.output[-1000:]}"
            )
        recorded = self.runner(slot.EDGE_ROLE)(opnsense.record(config), timeout=60)
        if not recorded.ok:
            raise Drifted(f"{edge} did not record the configuration it settled on "
                          f"(exit {recorded.exit_code}): {recorded.output[-1000:]}")
        return edge, reported

    def _settled(self, ran: Ran, expected: list[str], collector: tuple[str, int]) -> Ran:
        for _ in range(EDGE_SETTLE_READS):
            if self._edge_holds_its_configuration(ran, expected, collector):
                return ran
            time.sleep(EDGE_POLL)
            try:
                ran = self.runner(slot.EDGE_ROLE)(opnsense.verify(), timeout=60)
            except RangeUnavailable:
                continue
        return ran

    @staticmethod
    def _edge_holds_its_configuration(ran: Ran, expected: list[str], collector: tuple[str, int]) -> bool:
        return (
            ran.ok
            and set(expected) <= opnsense.held(ran.output)
            and opnsense.sensing(ran.output)
            and f"logs {collector[0]}:{collector[1]}" in opnsense.reported(ran.output)
            and opnsense.wan_rule_loaded(ran.output)
        )

    def _rebooted(self, edge: str, before: str) -> Ran:
        deadline = time.monotonic() + EDGE_REBOOT
        said = "it never answered"
        while time.monotonic() < deadline:
            try:
                ran = self.runner(slot.EDGE_ROLE)(opnsense.verify(), timeout=60)
            except RangeUnavailable as gone:
                said = str(gone)
            else:
                if opnsense.booted(ran.output) not in ("", before):
                    return ran
                said = "it had not rebooted yet"
            time.sleep(EDGE_POLL)
        raise Drifted(f"{edge} did not come back from its reboot within {EDGE_REBOOT}s: {said}")

    def configure_waf(self) -> tuple[str, tuple[str, ...]]:
        host = self.declared.host(GATEWAY_ROLE)
        audit = waf.audit_log((Path(self.build.source) / waf.MODSECURITY).read_text())
        collector = self._collector()
        ran = self.runner(GATEWAY_ROLE)(
            waf.command(), stdin=waf.forwarding(audit, collector, fabric.COLLECTOR_PORT),
            timeout=120,
        )
        if not ran.ok:
            raise Drifted(f"{host} did not take its log forwarding: {ran.output[-1000:]}")
        return host, (f"logs {audit} to {collector}:{fabric.COLLECTOR_PORT}",)

    def start_wargames(self) -> tuple[str, tuple[str, ...]]:
        host = self.declared.host(wargame_host.ROLE)
        entry = self.declared.hosts.get(host)
        if entry is None or not entry.wargames:
            raise Drifted(f"{host} fills {wargame_host.ROLE!r} and the declaration gives it no wargame to run")
        for wargame in entry.wargames:
            ran = self.runner(wargame_host.ROLE)(wargame_host.up(wargame), timeout=wargame_host.UP_TIMEOUT)
            if not ran.ok:
                raise Drifted(f"{host} did not start {wargame} (exit {ran.exit_code}): {ran.output[-1000:]}")
        return host, tuple(f"runs {wargame}" for wargame in entry.wargames)

    def open_collector(self) -> tuple[str, tuple[str, ...]]:
        roles = (slot.EDGE_ROLE, GATEWAY_ROLE, *sorted(self.declared.watches))
        senders = list(dict.fromkeys(
            self._address(role, self.declared.host(role), fabric.MANAGEMENT) for role in roles
        ))
        sending = {self.declared.host(role) for role in roles}
        elsewhere = [
            entry["addr"] for server in self._all(SERVERS, "servers")
            if slot.in_slot(server) and slot.slot_of(server) != self.slot
            and server["metadata"][slot.HOST] in sending
            for entries in (server.get("addresses") or {}).values() for entry in entries
        ]
        group = next(
            group for group in self._all(SECURITY_GROUPS, "security_groups")
            if group["name"] == fabric.REACH_GROUP
        )
        create, delete = fabric.hearing(group, senders, kept=elsewhere)
        for rule in delete:
            self.get(self._call(DELETE_RULE, rule=rule))
        for rule in create:
            self.get(self._call(CREATE_RULE), {"security_group_rule": rule})
        return self.declared.host(SCORER_ROLE), tuple(f"hears {sender}" for sender in senders)

    def _slot(self):
        networks, subnets, _, groups = self._fabric_standing()
        bound = fabric.bound(self.declared, networks, self.slot)
        ports = [
            port for network in bound.values()
            for port in self._all(PORTS, "ports", network=network["id"])
        ]
        ready = self._ready_images()
        plan = slot.plan(self.declared, networks, subnets, ports,
                         self._all(SERVERS, "servers"), ready, self.slot)
        return plan, bound, subnets, ports, groups, ready

    def _ready_images(self) -> dict[str, str]:
        return {
            found.host: found.image for found in self.plan_images().images
            if found.state == "ready"
        }

    def plan_slots(self) -> list[slot.Plan]:
        networks, subnets, _, _ = self._fabric_standing()
        servers = self._all(SERVERS, "servers")
        ready = self._ready_images()
        listed: dict[str, list] = {}
        plans = []
        for number in range(1, self.slots + 1):
            bound = fabric.bound(self.declared, networks, number)
            ports = [
                port for network in bound.values()
                for port in listed.setdefault(network["id"], self._all(PORTS, "ports", network=network["id"]))
            ]
            plans.append(slot.plan(self.declared, networks, subnets, ports, servers, ready, number))
        return plans

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
