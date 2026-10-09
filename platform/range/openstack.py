from __future__ import annotations

import ipaddress
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests
from dataclasses import dataclass, replace

from range import fabric, images, pfsense, slot, waf
from range.declared import Declaration
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
DELETE_IMAGE = "DELETE {glance}/v2/images/{image}"
FLAVORS = "GET {nova}/flavors"
ACTION = "POST {nova}/servers/{server}/action"
DELETE_SERVER = "DELETE {nova}/servers/{server}"
SECURITY_GROUPS = "GET {neutron}/v2.0/security-groups?project_id={project}"
CREATE_GROUP = "POST {neutron}/v2.0/security-groups"
CREATE_RULE = "POST {neutron}/v2.0/security-group-rules"
DELETE_GROUP = "DELETE {neutron}/v2.0/security-groups/{group}"
DELETE_RULE = "DELETE {neutron}/v2.0/security-group-rules/{rule}"
CREATE_PORT = "POST {neutron}/v2.0/ports"
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
GATEWAY_ROLE = "gateway"

SETTINGS = {
    "keystone": "FSL_OPENSTACK_KEYSTONE",
    "user": "FSL_OPENSTACK_USER",
    "password": "FSL_OPENSTACK_PASSWORD",
    "project": "FSL_OPENSTACK_PROJECT",
    "ssh_user": "FSL_OPENSTACK_SSH_USER",
    "ssh_key": "FSL_OPENSTACK_SSH_KEY",
    "region": "FSL_OPENSTACK_REGION",
    "interface": "FSL_OPENSTACK_INTERFACE",
    "source": "FSL_SOURCE",
    "base_image": "FSL_OPENSTACK_BASE_IMAGE",
    "flavor": "FSL_OPENSTACK_FLAVOR",
    "build_network": "FSL_OPENSTACK_BUILD_NETWORK",
    "platform": "FSL_OPENSTACK_PLATFORM",
}

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
    region: str = "RegionOne",
    interface: str = "public",
    source: str = "",
    base_image: str = "",
    flavor: str = "",
    build_network: str = "",
    platform: str = "",
) -> "OpenStack":
    given = {
        "keystone": keystone, "user": user, "password": password,
        "project": project, "ssh_user": ssh_user, "ssh_key": ssh_key,
    }
    missing = [SETTINGS[name] for name, value in given.items() if not value]
    if missing:
        raise RangeUnavailable(
            f"the OpenStack substrate reaches no cloud without "
            f"{', '.join(missing)}"
        )
    known = (keystone, user, password, project, ssh_user, ssh_key,
             region, interface)

    def rediscover() -> tuple[Cloud, object]:
        cloud = discover(
            keystone, user, password, project, ssh_user, ssh_key,
            region=region, interface=interface,
        )
        _connected[known] = (cloud, http_reader(cloud, password))
        return _connected[known]

    cloud, reader = _connected.get(known) or rediscover()
    build = Build(source=source, base_image=base_image, flavor=flavor,
                  network=build_network, platform=platform)
    return OpenStack(declared, cloud, get=reader, rediscover=rediscover, build=build)

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
) -> "Cloud":
    answered = _signed_in(keystone, user, password, project, timeout)

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
    )

def _signed_in(keystone: str, user: str, password: str, project: str, timeout: float):
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": user,
                        "domain": {"id": "default"},
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
            cloud.keystone, cloud.user, password, cloud.project, timeout
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


@dataclass(frozen=True)
class Build:
    source: str = ""
    base_image: str = ""
    flavor: str = ""
    network: str = ""
    platform: str = ""


class OpenStack:
    def __init__(
        self, declared: Declaration, cloud: Cloud, get, rediscover=None,
        build: Build = Build(),
    ):
        self.declared = declared
        self.cloud = cloud
        self.build = build
        self.get = get
        self.rediscover = rediscover
        self._shape: Shape | None = None
        self._generations: dict[str, str] = {}

    def describe(self) -> Shape:
        if self._shape is None:
            try:
                self._shape = self._read()
            except EndpointGone:
                if self.rediscover is None:
                    raise
                self.cloud, self.get = self.rediscover()
                self._shape = self._read()
        return self._shape

    def segments(self) -> tuple[Segment, ...]:
        return self.describe().segments

    def _read(self) -> Shape:
        origins = {origin.id: origin for origin in self.declared.origins}
        carriers = list(dict.fromkeys(
            origins[segment.id].segment if segment.id in origins else segment.id
            for segment in self.declared.segments
        ))
        wanted = ",".join(f"{SEGMENT_TAG}={carrier}" for carrier in carriers)
        bound = self._bind(self._all(NETWORKS, "networks", tags=wanted))
        servers = self._all(SERVERS, "servers")
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

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            address = self._address(role, host, segment_id)
            with tempfile.TemporaryDirectory() as scratch:
                said = Path(scratch) / "ssh.log"
                config = self._config(Path(scratch) / "ssh_config", address)
                command = self._ssh(address, stdin is not None, said, config,
                                    self._ssh_user(host))
                command.append(shlex.join(reporting(argv)))
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

    def _bind(self, networks: list[dict]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for network in networks:
            for tag in network.get("tags") or []:
                mark, _, segment_id = tag.partition("=")
                if mark != SEGMENT_TAG or not segment_id:
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
            Node(name=server["name"], address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(network_name, [])
            if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4
            and (inside is None or ipaddress.ip_address(entry["addr"]) in inside)
        ]
        return tuple(sorted(found, key=lambda node: node.name))

    def _sensors(self, servers: list[dict]) -> tuple[Sensor, ...]:
        standing = {server["name"] for server in servers}
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
                           groups, self._reached(networks))

    def ensure_fabric(self) -> fabric.Plan:
        public_key = self._public_key(make=True)
        networks, subnets, keypairs, groups = self._fabric_standing()
        plan = fabric.plan(self.declared, networks, subnets, keypairs, public_key,
                           groups, self._reached(networks))
        if plan.drifted:
            raise Drifted("; ".join(plan.drifted))
        carriers = {
            segment: network["id"]
            for segment, network in fabric.bound(self.declared, networks).items()
        }
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
            if name == fabric.RANGE_GROUP:
                self.get(self._call(CREATE_RULE), {"security_group_rule": {
                    "security_group_id": named[name], "direction": "ingress",
                    "ethertype": "IPv4",
                }})
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
        for network in fabric.bound(self.declared, networks).values():
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

    def _make_network(self, segment: str) -> str:
        created = self.get(self._call(CREATE_NETWORK), {
            "network": {"name": f"fsl-{segment}"}
        })["network"]
        try:
            self.get(self._call(TAG_NETWORK, network=created["id"]), {
                "tags": [f"{fabric.TAG}={segment}"]
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
        for found in missing:
            base = self._builder_base(self.declared.hosts[found.host].base or self.build.base_image)
            self.get(self._call(BOOT), {"server": {
                **base,
                "name": images.BUILDER + found.host,
                "user_data": images.user_data(made[found.host]),
                "metadata": {images.BUILDS: found.host, images.BUNDLE: found.bundle},
            }})
        for found in plan.images:
            if found.state == "built":
                self.get(self._call(ACTION, server=found.builder), {"os-stop": None})
            elif found.state == "stopped":
                self.get(self._call(ACTION, server=found.builder), {"createImage": {
                    "name": found.host, "metadata": {images.BUNDLE: found.bundle},
                }})
            elif found.state == "ready" and found.builder:
                self.get(self._call(DELETE_SERVER, server=found.builder))
        return self._image_plan(bundles)

    def clean_images(self) -> list[tuple[str, str]]:
        removed = images.removable(self.plan_images())
        for kind, ident in removed:
            gone = DELETE_IMAGE if kind == "image" else DELETE_SERVER
            self.get(self._call(gone, image=ident, server=ident))
        return removed

    def _bundles(self) -> tuple[images.Bundle, ...]:
        return tuple(
            images.bundle(Path(self.build.source), host, entry.setup, entry.files)
            for host, entry in self.declared.hosts.items()
            if entry.setup
        )

    def _prebuilt(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (host, entry.image)
            for host, entry in self.declared.hosts.items()
            if entry.image
        )

    def _image_plan(self, bundles) -> images.Plan:
        prebuilt = self._prebuilt()
        names = {bundle.host for bundle in bundles} | {image for _, image in prebuilt}
        found = [
            image for name in names
            for image in self.get(self._call(IMAGES, name=quote(name))).get("images") or []
        ]
        digests = {bundle.digest for bundle in bundles}
        builders = [
            server for server in self._all(SERVERS, "servers")
            if images.BUILDS in (server.get("metadata") or {})
        ]
        consoles = {
            server["id"]: self._console(server["id"])
            for server in builders
            if server.get("status") == "ACTIVE"
            and server["metadata"].get(images.BUNDLE) in digests
        }
        return images.plan(bundles, found, builders, consoles, prebuilt=prebuilt)

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
                f"{SETTINGS['base_image']} (or the host's base) to one it has exactly once"
            )
        return {
            "imageRef": bases[0]["id"], "flavorRef": self._flavor(),
            "networks": [{"uuid": self.build.network}], "config_drive": True,
        }

    def _flavor(self) -> str:
        flavor = next((
            entry["id"] for entry in self.get(self._call(FLAVORS)).get("flavors") or []
            if entry.get("name") == self.build.flavor
        ), None)
        if flavor is None:
            raise RangeUnavailable(
                f"the cloud has no flavor {self.build.flavor!r}; set "
                f"{SETTINGS['flavor']} to one it lists"
            )
        return flavor

    def plan_slot(self) -> slot.Plan:
        return self._slot()[0]

    def console(self, host: str) -> str:
        server = next(
            (s for s in self._all(SERVERS, "servers")
             if (s.get("metadata") or {}).get(slot.HOST) == host),
            None,
        )
        if server is None:
            raise RangeUnavailable(
                f"no server fills {host!r}, so it has no console to open"
            )
        said = self.get(
            self._call(ACTION, server=server["id"]),
            {"os-getVNCConsole": {"type": "novnc"}},
        )
        url = (said.get("console") or {}).get("url") or ""
        if not url:
            raise RangeUnavailable(f"{host} returned no console url")
        return url

    def ensure_slot(self) -> slot.Plan:
        plan, bound, subnets, ports, groups, ready = self._slot()
        if plan.blocked:
            raise Drifted("; ".join(plan.blocked))
        if not plan.boot:
            return plan
        group = next((g["id"] for g in groups if g["name"] == fabric.RANGE_GROUP), None)
        if group is None:
            raise Drifted(f"the fabric has no security group {fabric.RANGE_GROUP}; build the fabric first")
        edge = slot.edge_of(self.declared)
        for port in plan.ports:
            body = {"network_id": bound[port.segment]["id"], "name": port.name,
                    "security_groups": [group]}
            if port.fixed_ips:
                body["fixed_ips"] = [
                    {"subnet_id": subnet, "ip_address": address} for subnet, address in port.fixed_ips
                ]
            if port.host == edge and port.segment != fabric.MANAGEMENT:
                body["allowed_address_pairs"] = [{"ip_address": "0.0.0.0/0"}]
            ports.append(self.get(self._call(CREATE_PORT), {"port": body})["port"])
        named = {port["name"]: port for port in ports if port.get("name")}
        names = {
            named[slot.port_name(host, slot.NAMED_ON)]["fixed_ips"][0]["ip_address"]: list(entry.names)
            for host, entry in self.declared.hosts.items()
            if entry.names and slot.port_name(host, slot.NAMED_ON) in named
        }
        prefixes = {subnet["id"]: subnet["cidr"].split("/")[1] for subnet in subnets}
        outside = {origin.segment for origin in self.declared.origins}
        flavor = self._flavor()
        for host in plan.boot:
            entry = self.declared.hosts[host]
            facing = [named[slot.port_name(host, s)] for s in entry.segments if s in outside]
            server = {
                "name": host, "imageRef": ready[host], "flavorRef": flavor,
                "networks": [{"port": named[slot.port_name(host, s)]["id"]} for s in entry.segments],
                "config_drive": True, "key_name": fabric.KEYPAIR,
                "metadata": {slot.HOST: host},
            }
            if not entry.image:
                server["user_data"] = slot.user_data(
                    names,
                    mac=facing[0]["mac_address"] if facing else "",
                    addresses=tuple(
                        f"{fixed['ip_address']}/{prefixes[fixed['subnet_id']]}"
                        for port in facing for fixed in port["fixed_ips"]
                    ),
                )
            self.get(self._call(BOOT), {"server": server})
        self._shape = None
        return self._slot()[0]

    def teardown_slot(self) -> list[tuple[str, str]]:
        hosts = self.declared.hosts
        bound = fabric.bound(self.declared, self._all(PROJECT_NETWORKS, "networks"))
        made = {slot.port_name(host, s) for host, entry in hosts.items() for s in entry.segments}
        steps = [
            ("server", server["id"]) for server in self._all(SERVERS, "servers")
            if (server.get("metadata") or {}).get(slot.HOST) in hosts
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

    def rebuild_slot(self) -> list[tuple[str, str]]:
        plan, _bound, _subnets, _ports, _groups, ready = self._slot()
        if plan.blocked:
            raise Drifted("; ".join(plan.blocked))
        if plan.boot:
            raise Drifted(
                f"the slot is not fully standing, so there is nothing to reset "
                f"for {', '.join(plan.boot)}; provision it first"
            )
        missing = [host for host, _server, _status in plan.standing if host not in ready]
        if missing:
            raise Drifted(
                f"image {', '.join(missing)} is not ready, so rebuilding would "
                f"wipe some VMs and leave others; make the images ready first"
            )
        rebuilt = []
        for host, server, _status in plan.standing:
            self.get(self._call(ACTION, server=server), {"rebuild": {"imageRef": ready[host]}})
            rebuilt.append((host, server))
        self._shape = None
        return rebuilt

    def configure_slot(self) -> list[tuple[str, tuple[str, ...]]]:
        return [self.configure_edge(), self.configure_waf(), self.open_collector()]

    def address(self, role: str) -> str:
        return self._address(role, self.declared.host(role), fabric.MANAGEMENT)

    def _collector(self) -> str:
        return self.address(SCORER_ROLE)

    def configure_edge(self) -> tuple[str, tuple[str, ...]]:
        source = Path(self.build.source)
        collector = f"{self._collector()}:{fabric.COLLECTOR_PORT}"
        wanted = pfsense.settings(self.describe().segments, self.declared,
                                  (source / pfsense.RULES).read_text(), collector)
        template = (source / pfsense.TEMPLATE).read_text()
        ran = self.runner(slot.EDGE_ROLE)(
            pfsense.command(), stdin=pfsense.playback(wanted, template), timeout=300,
        )
        expected = [gateway["address"] for gateway in [wanted["wan"], *wanted["aliases"]]]
        missing = [address for address in expected if address not in pfsense.held(ran.output)]
        reported = pfsense.reported(ran.output)
        sensing = pfsense.sensing(ran.output)
        logging = f"logs {collector}" in reported
        wan_rule = pfsense.wan_rule_loaded(ran.output)
        edge = slot.edge_of(self.declared)
        if not ran.ok or missing or not sensing or not logging or not wan_rule:
            raise Drifted(
                f"{edge} playback exited {ran.exit_code}, does not hold "
                f"{', '.join(missing) or 'nothing missing'}, its sensor is "
                f"{'running' if sensing else 'not running'}, it "
                f"{'logs' if logging else 'does not log'} to {collector}, and "
                f"its wan pass rule is {'in pf' if wan_rule else 'not loaded into pf'}: "
                f"{ran.output[-1000:]}"
            )
        return edge, reported

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

    def open_collector(self) -> tuple[str, tuple[str, ...]]:
        senders = [
            self._address(role, self.declared.host(role), fabric.MANAGEMENT)
            for role in (slot.EDGE_ROLE, GATEWAY_ROLE)
        ]
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

    def _slot(self):
        networks, subnets, _, groups = self._fabric_standing()
        bound = fabric.bound(self.declared, networks)
        ports = [
            port for network in bound.values()
            for port in self._all(PORTS, "ports", network=network["id"])
        ]
        ready = {
            found.host: found.image for found in self.plan_images().images
            if found.state == "ready"
        }
        plan = slot.plan(self.declared, networks, subnets, ports,
                         self._all(SERVERS, "servers"), ready)
        return plan, bound, subnets, ports, groups, ready

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
