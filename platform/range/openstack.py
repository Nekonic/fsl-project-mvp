from __future__ import annotations

import hashlib
import ipaddress
import json
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

import requests

from range import fabric, pool, sandbox, wiring
from range.declared import Declaration, Host
from rules import suricata
from range.ports import (
    Drifted, Node, Ran, RangeUnavailable, Segment, Sensor, Shape, execute,
    reported, reporting,
)

NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags-any={tags}"
SLOT_NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags={tags}"
SLOT_PORTS = "GET {neutron}/v2.0/ports?project_id={project}&tags={tags}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"
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
OWN_IMAGES = "GET {glance}/v2/images?owner={project}&visibility=private&limit=100"
IMAGES = "GET {glance}/v2/images?limit=100"
DELETE_IMAGE = "DELETE {glance}/v2/images/{image}"
DELETE_SERVER = "DELETE {nova}/servers/{server}"
SECURITY_GROUPS = "GET {neutron}/v2.0/security-groups?project_id={project}"
CREATE_GROUP = "POST {neutron}/v2.0/security-groups"
CREATE_RULE = "POST {neutron}/v2.0/security-group-rules"
DELETE_GROUP = "DELETE {neutron}/v2.0/security-groups/{group}"
CREATE_PORT = "POST {neutron}/v2.0/ports"
DELETE_PORT = "DELETE {neutron}/v2.0/ports/{port}"
ATTACH = "POST {nova}/servers/{server}/os-interface"
STACKS = "GET {heat}/stacks?tags=" + "cr-range"
CREATE_STACK = "POST {heat}/stacks"
DELETE_STACK = "DELETE {heat}/stacks/{name}/{stack}"

DELETES = {
    "subnet": DELETE_SUBNET, "network": DELETE_NETWORK, "keypair": DELETE_KEYPAIR,
    "group": DELETE_GROUP, "port": DELETE_PORT, "server": DELETE_SERVER, "image": DELETE_IMAGE,
}

FIXED = "OS-EXT-IPS:type"
LAUNCHED = "OS-SRV-USG:launched_at"
PAGE_LIMIT = 50
BUILDS = "cr_image"
OLD_HOST = "cr_host"
OLD_BUNDLE = "cr_bundle"
SLOT_KEY = "cr_slot"
NODE_KEY = "cr_node"
IMAGE = "cr-{role}-bake1"
BASELINE_RULES = "deploy/suricata/rules/local.rules"
STACK_TIMEOUT_MINUTES = 30

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
SENSOR_ROLES = ("sensor",)
GONE_WAIT = 300
GONE_POLL = 3
ELEVATED = ("sudo",)
SET_UP = ["sh", "-c", f"if [ -f {sandbox.READY} ]; then echo ready; elif [ -f {sandbox.FAILED} ]; then echo failed; "
                      f"else echo setting-up; fi"]
DOCKER_NETWORKS = ["sh", "-c", "docker network inspect $(docker network ls -q --filter driver=bridge)"]
WARGAMES_ROLE = "wargames"
MANAGER = "ubuntu"

SETTINGS = {
    "keystone": "CR_OPENSTACK_KEYSTONE",
    "user": "CR_OPENSTACK_USER",
    "domain": "CR_OPENSTACK_DOMAIN",
    "password": "CR_OPENSTACK_PASSWORD_FILE",
    "project": "CR_OPENSTACK_PROJECT",
    "ssh_user": "CR_OPENSTACK_SSH_USER",
    "ssh_key": "CR_OPENSTACK_SSH_KEY",
    "region": "CR_OPENSTACK_REGION",
    "interface": "CR_OPENSTACK_INTERFACE",
    "source": "CR_SOURCE",
    "availability_zone": "CR_OPENSTACK_AVAILABILITY_ZONE",
    "subnets": "CR_OPENSTACK_SUBNETS",
    "platform": "CR_OPENSTACK_PLATFORM",
    "pool": "CR_OPENSTACK_POOL",
    "target_tag": "CR_OPENSTACK_TARGET_TAG",
    "images": "CR_OPENSTACK_IMAGES",
    "flavors": "CR_OPENSTACK_FLAVORS",
}

_connected: dict[tuple, tuple["Cloud", object]] = {}
_set_up: set[str] = set()
_held: dict[tuple[str, int], "Held"] = {}
_booting = threading.Lock()


class EndpointGone(RangeUnavailable):
    pass


HOT_VERSION = "2021-04-16"
STACK = "cr-slot-{slot}"
STACK_TAG = "cr-range"
SLOT_TAG = "cr.slot={slot}"
WARGAME_TAG = "cr.wargame="
DIGEST_TAG = "cr.digest="
CONTROL = "control"
STACK_PARAMETERS = ("key_name", "control_network", "control_group", "senders_group")


def stack_name(slot: int) -> str:
    return STACK.format(slot=slot)


def _tags(plan: sandbox.Sandbox, **marks: str) -> list[str]:
    return [SLOT_TAG.format(slot=plan.slot), *(f"cr.{key}={value}" for key, value in marks.items())]


def _lan_rules(plan: sandbox.Sandbox, lan: sandbox.Lan) -> list[dict]:
    if lan.name == plan.logged:
        return [{"direction": "ingress", "protocol": "tcp", "port_range_min": sandbox.SHIPPED_PORT,
                 "port_range_max": sandbox.SHIPPED_PORT, "remote_ip_prefix": cidr} for cidr in lan.cidrs]
    foreign = any(port.pairs for port in plan.ports if port.lan == lan.name)
    return [{"direction": "ingress", "remote_ip_prefix": cidr}
            for cidr in ((sandbox.EVERYWHERE,) if foreign else lan.cidrs)]


def _port_name(port: sandbox.Port) -> str:
    return f"port_{port.node}_{port.lan}"


def _subnet_of(plan: sandbox.Sandbox, port: sandbox.Port) -> str:
    lan = next(lan for lan in plan.lans if lan.name == port.lan)
    at = next(at for at, cidr in enumerate(lan.cidrs)
              if ipaddress.ip_address(port.address) in ipaddress.ip_network(cidr))
    return f"subnet_{lan.name}_{at}"


def template(plan: sandbox.Sandbox, availability_zone: str = "") -> dict:
    prefix = stack_name(plan.slot)
    roles = sorted({node.role for node in plan.nodes})
    parameters = {name: {"type": "string"} for name in STACK_PARAMETERS}
    parameters.update({f"{kind}_{role}": {"type": "string"} for kind in ("image", "flavor") for role in roles})
    resources: dict[str, dict] = {}
    for lan in plan.lans:
        resources[f"net_{lan.name}"] = {"type": "OS::Neutron::Net", "properties": {
            "name": f"{prefix}-{lan.name}", "tags": _tags(plan, lan=lan.name)}}
        for at, cidr in enumerate(lan.cidrs):
            resources[f"subnet_{lan.name}_{at}"] = {"type": "OS::Neutron::Subnet", "properties": {
                "name": f"{prefix}-{lan.name}-{at}", "network": {"get_resource": f"net_{lan.name}"},
                "cidr": cidr, "enable_dhcp": False, "gateway_ip": None}}
        resources[f"group_{lan.name}"] = {"type": "OS::Neutron::SecurityGroup", "properties": {
            "name": f"{prefix}-{lan.name}", "rules": _lan_rules(plan, lan)}}
    for node in plan.nodes:
        control_groups = [{"get_param": "control_group"}]
        if node.role == "infra":
            control_groups.append({"get_param": "senders_group"})
        resources[f"port_{node.name}_{CONTROL}"] = {"type": "OS::Neutron::Port", "properties": {
            "name": f"{prefix}-{node.name}-{CONTROL}", "network": {"get_param": "control_network"},
            "security_groups": control_groups, "tags": _tags(plan, node=node.name, lan=CONTROL)}}
        for port in node.ports:
            properties = {
                "name": f"{prefix}-{node.name}-{port.lan}", "network": {"get_resource": f"net_{port.lan}"},
                "fixed_ips": [{"subnet": {"get_resource": _subnet_of(plan, port)}, "ip_address": port.address}],
                "tags": _tags(plan, node=node.name, device=port.device, lan=port.lan),
            }
            if port.secured:
                properties["security_groups"] = [{"get_resource": f"group_{port.lan}"}]
            else:
                properties["port_security_enabled"] = False
            if port.pairs:
                properties["allowed_address_pairs"] = [{"ip_address": pair} for pair in port.pairs]
            resources[_port_name(port)] = {"type": "OS::Neutron::Port", "properties": properties}
        server = {
            "name": f"{prefix}-{node.name.removeprefix('cr-')}",
            "image": {"get_param": f"image_{node.role}"}, "flavor": {"get_param": f"flavor_{node.role}"},
            "key_name": {"get_param": "key_name"}, "config_drive": True,
            "networks": [{"port": {"get_resource": f"port_{node.name}_{CONTROL}"}}]
            + [{"port": {"get_resource": _port_name(port)}} for port in node.ports],
            "user_data_format": "RAW", "user_data": node.user_data,
            "metadata": {"cr_slot": str(plan.slot), "cr_node": node.name, "cr_wargame": plan.wargame},
        }
        if availability_zone:
            server["availability_zone"] = availability_zone
        resources[f"server_{node.name}"] = {"type": "OS::Nova::Server", "properties": server}
    return {"heat_template_version": HOT_VERSION, "description": f"{prefix}: {plan.wargame}",
            "parameters": parameters, "resources": resources}


def stack_digest(rendered: dict, parameters: dict) -> str:
    hashed = hashlib.sha256(json.dumps([rendered, parameters], sort_keys=True).encode())
    return hashed.hexdigest()[:16]


def stack_body(plan: sandbox.Sandbox, rendered: dict, parameters: dict, digest: str, timeout_minutes: int) -> dict:
    return {"stack_name": stack_name(plan.slot), "template": rendered, "parameters": parameters,
            "tags": ",".join([STACK_TAG, SLOT_TAG.format(slot=plan.slot), WARGAME_TAG + plan.wargame,
                              DIGEST_TAG + digest]),
            "timeout_mins": timeout_minutes, "disable_rollback": True}


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
    flavor: str = "dba.small",
    availability_zone: str = "",
    subnets: str = "",
    platform: str = "",
    pool: str = "",
    target_tag: str = "",
    images: str = "",
    flavors: str = "",
) -> "OpenStack":
    given = {
        "keystone": keystone, "user": user, "password": password,
        "project": project, "ssh_user": ssh_user, "ssh_key": ssh_key,
        "region": region, "interface": interface, "domain": domain,
    }
    given["ssh_user"] = ssh_user = ssh_user or MANAGER
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
        counts = _counts(pool)
        build = Build(
            source=source, flavor=flavor, availability_zone=availability_zone, inside=pairs(subnets),
            platform=platform, slots=sum(count for _, count in counts) or 1, pool=counts, target_tag=target_tag,
            images=pairs(images), flavors=pairs(flavors),
        )
    except ValueError as error:
        raise RangeUnavailable(
            f"the cloud settings ({', '.join(SETTINGS[n] for n in ('subnets', 'pool', 'images', 'flavors'))}) "
            f"do not parse: {error}; they come from cloud.yaml through the Heat stack"
        ) from error
    cloud, reader = _connected.get(known) or (None, None)
    reach = Cloud(keystone=keystone, neutron="", nova="", project=project, user=user,
                  ssh_user=ssh_user, ssh_key=ssh_key, domain=domain)
    return OpenStack(declared, cloud, get=reader, rediscover=rediscover, build=build, reach=reach)


def _counts(text: str) -> tuple[tuple[str, int], ...]:
    counts = tuple((wargame, int(count)) for wargame, count in pairs(text).items())
    if any(count < 0 for _, count in counts) or (counts and not sum(count for _, count in counts)):
        raise ValueError(f"{SETTINGS['pool']} is {text!r}; a pool holds one slot or more")
    return counts


def forget() -> None:
    _connected.clear()
    _set_up.clear()
    _held.clear()


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
    domain: str = "Default",
) -> "Cloud":
    answered = _signed_in(keystone, user, password, project, timeout, domain)

    catalog = (answered.json().get("token") or {}).get("catalog") or []
    return Cloud(
        keystone=keystone,
        neutron=_endpoint(catalog, "network", region, interface),
        nova=_endpoint(catalog, "compute", region, interface),
        glance=_endpoint(catalog, "image", region, interface),
        heat=_endpoint(catalog, "orchestration", region, interface),
        project=project,
        user=user,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        domain=domain,
    )


def _signed_in(keystone: str, user: str, password: str, project: str, timeout: float,
               domain: str = "Default"):
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": user,
                        "domain": {"name": domain},
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


def _on_management(shape: Shape, host: str) -> str:
    for segment in shape.segments:
        if segment.id != fabric.MANAGEMENT:
            continue
        for node in segment.nodes:
            if node.name == host:
                return node.address
    return ""


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


def _metadata(server: dict, key: str) -> str:
    return str((server.get("metadata") or {}).get(key) or "")


def known_as(server: dict) -> str:
    return _metadata(server, NODE_KEY) or server["name"]


def _tag(stack: dict, prefix: str) -> str:
    tags = stack.get("tags") or []
    tags = tags.split(",") if isinstance(tags, str) else tags
    return next((tag[len(prefix):] for tag in tags if tag.startswith(prefix)), "")


def _slot_of(stack: dict) -> int:
    value = _tag(stack, "cr.slot=")
    return int(value) if value.isdigit() else 0


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
    domain: str = "Default"
    heat: str = ""


@dataclass(frozen=True)
class Held:
    stack: str
    addresses: dict[str, str]
    generations: dict[str, str]
    docker: tuple | None = None


@dataclass(frozen=True)
class Build:
    source: str = ""
    flavor: str = ""
    availability_zone: str = ""
    inside: dict = field(default_factory=dict)
    platform: str = ""
    slots: int = 1
    pool: tuple[tuple[str, int], ...] = ()
    target_tag: str = ""
    images: dict = field(default_factory=dict)
    flavors: dict = field(default_factory=dict)

    def image(self, role: str) -> str:
        return self.images.get(role) or IMAGE.format(role=role)

    def flavor_of(self, role: str) -> str:
        return self.flavors.get(role) or self.flavor


class OpenStack:
    def __init__(
        self, declared: Declaration, cloud: Cloud | None, get, rediscover=None,
        build: Build = Build(), slot: int = 1, reach: Cloud | None = None,
    ):
        self.declared = declared
        self._cloud = cloud
        self.build = build
        self._get = get
        self.rediscover = rediscover
        self.slot = slot
        self.reach = reach or cloud
        self._shape: Shape | None = None
        self._generations: dict[str, str] = {}

    @property
    def cloud(self) -> Cloud:
        if self._cloud is None:
            self._cloud, self._get = self.rediscover()
        return self._cloud

    @cloud.setter
    def cloud(self, value: Cloud) -> None:
        self._cloud = value

    @property
    def get(self):
        if self._get is None:
            self._cloud, self._get = self.rediscover()
        return self._get

    @get.setter
    def get(self, value) -> None:
        self._get = value

    def _reaching(self) -> Cloud:
        return self._cloud or self.reach or self.cloud

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
        return OpenStack(self.declared, self._cloud, self._get, self.rediscover, self.build,
                         slot=number, reach=self.reach)

    def every_slot(self) -> list["OpenStack"]:
        return [self.in_slot(number) for number in range(1, self.slots + 1)]

    @property
    def wargame(self) -> str:
        return pool.assigned(self.slot, self.declared.wargames, self.build.pool)

    @property
    def _key(self) -> tuple[str, int]:
        return self._reaching().project, self.slot

    def _definition(self, wargame: str) -> sandbox.Definition:
        definition = self.declared.definitions.get(wargame)
        if definition is None:
            raise RangeUnavailable(f"slot {self.slot} is asked to run {wargame!r}, which has no topology.yaml")
        return definition

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

    def _mine(self, server: dict) -> bool:
        return _metadata(server, SLOT_KEY) in ("", str(self.slot))

    def _read(self) -> Shape:
        carriers = fabric.carried(self.declared)
        wanted = ",".join(f"{SEGMENT_TAG}={carrier}" for carrier in carriers)
        bound = fabric.bound(self.declared, self._all(NETWORKS, "networks", tags=wanted))
        servers = [server for server in self._all(SERVERS, "servers") if self._mine(server)]
        self._generations = _generations(servers)
        definition = self._definition(self.wargame)
        edge = definition.filling("edge").name
        kali = sandbox.addressed(definition.ports, self.declared.origins, self.declared.default_origin)
        internet = next(port.lan for port in kali if port.origins)
        router = next(port.address for port in kali if port.device == edge and port.lan == internet)
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")
        standing = any(_metadata(server, SLOT_KEY) == str(self.slot) for server in servers)
        segments = []
        for declared in self.declared.segments:
            origin = next((one for one in self.declared.origins if one.id == declared.id), None)
            if origin is not None:
                nodes = tuple(Node(name=attacker, address=address)
                              for address in sandbox.origin_addresses(origin.subnet, origin.addresses))
                segments.append(Segment(id=declared.id, name=declared.name, origin=declared.origin,
                                        subnet=origin.subnet, network=f"{stack_name(self.slot)}-{internet}",
                                        gateway=router, nodes=nodes))
            elif declared.id in carriers:
                network = bound.get(declared.id)
                if network is None:
                    raise RangeUnavailable(
                        f"the declaration names the segment {declared.id!r} and no network of "
                        f"project {self.cloud.project!r} is tagged {SEGMENT_TAG}={declared.id}")
                held = next((subnet for subnet in self._all(SUBNETS, "subnets", network=network["id"])
                             if subnet.get("ip_version", 4) == 4), {})
                cidr = held.get("cidr", "")
                segments.append(Segment(id=declared.id, name=declared.name, origin=declared.origin, subnet=cidr,
                                        network=network["id"], gateway=held.get("gateway_ip") or "",
                                        nodes=self._nodes(network["name"], servers, cidr)))
            else:
                raise RangeUnavailable(f"the declaration names the segment {declared.id!r}, which "
                                       f"neither a slot nor the fabric carries")
        sensors = tuple(Sensor(name=name, watches=host) for name, host in self.declared.watching() if standing)
        return Shape(segments=tuple(segments), sensors=sensors)

    def _nodes(self, network_name: str, servers: list[dict], cidr: str = "") -> tuple[Node, ...]:
        inside = ipaddress.ip_network(cidr) if cidr else None
        found = [
            Node(name=known_as(server), address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(network_name, [])
            if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4
            and (inside is None or ipaddress.ip_address(entry["addr"]) in inside)
        ]
        return tuple(sorted(found, key=lambda node: node.name))

    def _address(self, host: str) -> str:
        held = _held.get(self._key)
        if held is not None and held.addresses.get(host):
            self._generations.update(held.generations)
            return held.addresses[host]
        address = _on_management(self.describe(), host)
        if not address:
            raise RangeUnavailable(f"{host} stands on no {fabric.MANAGEMENT} address this platform can reach")
        return address

    def _placed(self, role: str) -> tuple[str, str]:
        device = self.declared.host(role)
        entry = self.declared.hosts.get(device) or Host()
        return entry.node or device, entry.container

    def address(self, role: str) -> str:
        return self._address(self._placed(role)[0])

    def runner(self, role: str, segment_id: str = ""):
        node, container = self._placed(role)
        return self._shell(node, container)

    def _sent(self, argv: list[str], container: str, reads_input: bool, tty: bool = False) -> list[str]:
        if not container:
            return [*ELEVATED, *argv]
        flags = ["-i"] if reads_input else []
        flags += ["-t"] if tty else []
        return [*ELEVATED, "docker", "exec", *flags, container, *argv]

    def _shell(self, node: str, container: str = "", address: str = ""):
        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            reached = address or self._address(node)
            with tempfile.TemporaryDirectory() as scratch:
                said = Path(scratch) / "ssh.log"
                config = self._config(Path(scratch) / "ssh_config", reached)
                command = self._ssh(reached, stdin is not None, said, config)
                command.append(shlex.join(self._sent(reporting(argv), container, stdin is not None)))
                done = execute(node, command, stdin, timeout)
                logged = said.read_text() if said.exists() else ""
                complaint = " ".join(filter(None, (
                    line.strip("@ ") for line in
                    f"{logged}\n{done.stderr or ''}".splitlines()
                )))
            ran = reported(done)
            if ran is None:
                raise RangeUnavailable(
                    f"{container or node} at {reached} never reported the command finishing: "
                    + (complaint[:1000] or "the connection ended before it did")
                )
            return ran

        return run

    def terminal(self, host: str) -> tuple[str, str, str]:
        node = (self.declared.hosts.get(host) or Host()).node
        if not node:
            raise RangeUnavailable(f"{host} is no device of a slot to open a terminal on")
        address = self._address(node)
        return address, self._generations.get(address, "") or address, node

    def wiring(self) -> wiring.Wiring:
        tags = quote(SLOT_TAG.format(slot=self.slot))
        definition = self._definition(self.wargame)
        kali = sandbox.addressed(definition.ports, self.declared.origins, self.declared.default_origin)
        extra = {port.device: port.extra for port in kali if port.extra}
        return wiring.from_neutron(self._all(SLOT_NETWORKS, "networks", tags=tags),
                                   self._all(PROJECT_SUBNETS, "subnets"),
                                   self._all(SLOT_PORTS, "ports", tags=tags), extra, self._docker())

    def _docker(self) -> tuple:
        held = _held.get(self._key)
        if held is not None and held.docker is not None:
            return held.docker
        found = self._docker_read()
        if held is not None and found:
            _held[self._key] = Held(held.stack, held.addresses, held.generations, found)
        return found

    def _docker_read(self) -> tuple:
        containers = {host.container: name for name, host in self.declared.hosts.items() if host.container}
        try:
            said = self.runner(WARGAMES_ROLE)(DOCKER_NETWORKS, timeout=30)
            return wiring.from_docker(json.loads(said.output) if said.ok else [], containers)
        except (RangeUnavailable, ValueError):
            return ()

    def _ssh(self, address: str, reads_input: bool, log: Path, config: Path) -> list[str]:
        command = ["ssh", "-F", str(config)]
        if not reads_input:
            command.append("-n")
        return command + [
            "-i", self._reaching().ssh_key,
            "-E", str(log),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "LogLevel=ERROR",
            f"{self._reaching().ssh_user}@{address}",
        ]

    def _config(self, written: Path, address: str) -> Path:
        included = []
        reaching = self._reaching()
        if reaching.ssh_config:
            linked = written.with_name("deployment_ssh_config")
            linked.symlink_to(Path(reaching.ssh_config).expanduser().resolve())
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
                    f"asked to start {image!r} on {segment_id!r}; a tool runs on the slot's "
                    f"attacker {attacker!r} and no other box"
                )
            return self.runner(ATTACKER_ROLE)(argv, timeout=timeout)

        return launch

    def users_box(self, segment_ids: list[str], image: str):
        attacker = self.declared.roles.get(ATTACKER_ROLE, "")
        if image != attacker:
            raise RangeUnavailable(
                f"asked to run customers from {image!r}; they run on the slot's attacker "
                f"{attacker!r}, which stands on every origin"
            )
        return self.runner(ATTACKER_ROLE)

    def opened(self, role: str, argv: list[str]) -> socket.socket:
        node, container = self._placed(role)
        address = self._address(node)
        scratch = Path(tempfile.mkdtemp())
        config = self._config(scratch / "ssh_config", address)
        command = self._ssh(address, True, scratch / "ssh.log", config)
        ours, theirs = socket.socketpair()
        try:
            piped = subprocess.Popen(command + [shlex.join(self._sent(argv, container, True))], stdin=theirs,
                                     stdout=theirs, stderr=subprocess.DEVNULL)
        except OSError as exc:
            ours.close()
            shutil.rmtree(scratch, ignore_errors=True)
            raise RangeUnavailable(f"could not reach {node}: {exc}") from exc
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
        if plan.collector:
            self.get(self._call(CREATE_RULE), {"security_group_rule": fabric.collector_rule(
                named[fabric.REACH_GROUP], named[fabric.SENDERS_GROUP])})
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
        left = [port["id"] for port in self._all(PORTS, "ports", network=network)
                if port.get("name") == name and _detached(port)]
        for extra in left[1:]:
            self.get(self._call(DELETE_PORT, port=extra))
        port = left[0] if left else self.get(self._call(CREATE_PORT), {"port": {
            "network_id": network, "name": name, "security_groups": [group],
        }})["port"]["id"]
        try:
            self.get(self._call(ATTACH, server=self.build.platform), {
                "interfaceAttachment": {"port_id": port}
            })
        except RangeUnavailable:
            if not left:
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
        private = Path(self._reaching().ssh_key).expanduser()
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

    def _stacks(self) -> dict[int, dict]:
        return {_slot_of(stack): stack for stack in self._all(STACKS, "stacks")
                if stack.get("stack_status") != "DELETE_COMPLETE"}

    def _collector(self, servers: list[dict]) -> str:
        scorer = self.declared.roles.get(SCORER_ROLE, "")
        network = fabric.network_name(fabric.MANAGEMENT)
        for server in servers:
            if server.get("id") == self.build.platform or known_as(server) == scorer:
                for entry in (server.get("addresses") or {}).get(network, []):
                    if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4:
                        return entry["addr"]
        return ""

    def _sandbox(self, wargame: str, collector: str) -> sandbox.Sandbox:
        return sandbox.plan(self._definition(wargame), self.slot, self.declared.origins,
                            self.declared.default_origin, collector, (self._reaching().ssh_user, self._public_key()),
                            self.build.target_tag)

    def _chosen(self, plan: sandbox.Sandbox) -> dict[str, str]:
        roles = sorted({node.role for node in plan.nodes})
        return {**{f"image_{role}": self.build.image(role) for role in roles},
                **{f"flavor_{role}": self.build.flavor_of(role) for role in roles}}

    def _rendered(self, wargame: str, collector: str) -> tuple[sandbox.Sandbox, dict, str]:
        plan = self._sandbox(wargame, collector)
        rendered = template(plan, self.build.availability_zone)
        return plan, rendered, stack_digest(rendered, self._chosen(plan))

    def _provisioned(self, server: dict) -> str:
        if server["id"] in _set_up:
            return pool.ACTIVE
        address = next((entry["addr"] for entry in
                        (server.get("addresses") or {}).get(fabric.network_name(fabric.MANAGEMENT), [])
                        if entry.get(FIXED) == "fixed"), "")
        if not address:
            return pool.SETTING_UP
        self._generations.update(_generations([server]))
        try:
            said = self._shell(known_as(server), address=address)(SET_UP, timeout=30).output
        except RangeUnavailable:
            return pool.SETTING_UP
        if said.startswith("ready"):
            _set_up.add(server["id"])
            return pool.ACTIVE
        return pool.SETUP_FAILED if said.startswith("failed") else pool.SETTING_UP

    def _unbootable(self, collector: str) -> list[str]:
        reasons = []
        if not collector:
            reasons.append(f"the platform stands on no {fabric.network_name(fabric.MANAGEMENT)} address, so a "
                           f"slot's logs and clock would reach nothing; build the fabric first")
        if not self.declared.wargames:
            reasons.append("no wargame has a topology.yaml, so a slot has nothing to run")
        held = {image.get("name") for image in self._all(IMAGES, "images") if image.get("status") == "active"}
        reasons += [f"no active image {self.build.image(role)} in Glance for the slot's {role}; bake it from "
                    f"deploy/roles/{role}/ or name another in compute.images.{role}"
                    for role in sandbox.ROLES if self.build.image(role) not in held]
        return reasons

    def _plan(self, stack: dict | None, servers: list[dict], collector: str) -> pool.Plan:
        name = stack_name(self.slot)
        if stack is None:
            return pool.Plan(boot=(name,), blocked=tuple(self._unbootable(collector)), slot=self.slot,
                             wargame=self.wargame)
        wargame = _tag(stack, WARGAME_TAG) or self.wargame
        status = str(stack.get("stack_status") or "")
        mine = sorted((server for server in servers if _metadata(server, SLOT_KEY) == str(self.slot)),
                      key=known_as)
        standing = tuple((known_as(server), server["id"],
                          pool.server_status(status, str(server.get("status") or ""),
                                             self._provisioned(server) if status == pool.COMPLETE else ""))
                         for server in mine) or ((name, stack["id"], pool.stack_state(status)),)
        failures = ((f"{name} is {status}: {stack.get('stack_status_reason') or 'Heat gave no reason'}",)
                    if pool.stack_state(status) == pool.FAILED else ())
        self._hold(str(stack["id"]), mine if status == pool.COMPLETE and standing and all(
            state == pool.ACTIVE for _, _, state in standing) else [])
        stale = ()
        if collector and wargame in self.declared.definitions and not status.startswith("DELETE"):
            stale = (name,) if _tag(stack, DIGEST_TAG) != self._rendered(wargame, collector)[2] else ()
        return pool.Plan(standing=standing, slot=self.slot, stale=stale, wargame=wargame, stack=status,
                         stack_id=str(stack["id"]), failures=failures)

    def _hold(self, stack: str, servers: list[dict]) -> None:
        held = _held.get(self._key)
        if not servers:
            _held.pop(self._key, None)
            return
        if held is not None and held.stack == stack:
            return
        network = fabric.network_name(fabric.MANAGEMENT)
        addresses = {known_as(server): entry["addr"] for server in servers
                     for entry in (server.get("addresses") or {}).get(network, [])
                     if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4}
        _held[self._key] = Held(stack, addresses, _generations(servers))
        docker = self._docker_read()
        if docker:
            _held[self._key] = replace(_held[self._key], docker=docker)

    def plan_slot(self) -> pool.Plan:
        servers = self._all(SERVERS, "servers")
        return self._plan(self._stacks().get(self.slot), servers, self._collector(servers))

    def plan_slots(self) -> list[pool.Plan]:
        stacks, servers = self._stacks(), self._all(SERVERS, "servers")
        collector = self._collector(servers)
        return [self.in_slot(number)._plan(stacks.get(number), servers, collector)
                for number in range(1, self.slots + 1)]

    def ensure_slot(self, renew: bool = True, wargame: str = "") -> pool.Plan:
        with _booting:
            plan = self.plan_slot()
            if plan.blocked:
                raise Drifted("; ".join(plan.blocked))
            wanted = wargame or self.wargame or plan.wargame
            deleted = ()
            if plan.boot:
                self._create(wanted)
            elif renew and not plan.stack.startswith("DELETE") and (
                    plan.failures or plan.stale or not plan.serves(wanted)):
                self._delete(plan.stack_id)
                deleted = ((stack_name(self.slot), plan.stack_id),)
        self._shape = None
        return replace(self.plan_slot(), rebuilt=deleted)

    def _create(self, wargame: str) -> None:
        _held.pop(self._key, None)
        servers = self._all(SERVERS, "servers")
        plan, rendered, digest = self._rendered(wargame, self._collector(servers))
        self.get(self._call(CREATE_STACK), stack_body(plan, rendered, {**self._chosen(plan), **self._fabric_ids()},
                                                      digest, STACK_TIMEOUT_MINUTES))

    def _fabric_ids(self) -> dict[str, str]:
        networks, _, _, groups = self._fabric_standing()
        management = fabric.bound(self.declared, networks).get(fabric.MANAGEMENT)
        named = {group["name"]: group["id"] for group in groups}
        missing = [name for name in (fabric.MANAGEMENT_GROUP, fabric.SENDERS_GROUP) if name not in named]
        if management is None or missing:
            raise Drifted(f"the fabric has no {fabric.MANAGEMENT} network or no security group "
                          f"{', '.join(missing) or '-'}; build the fabric first")
        return {"key_name": fabric.KEYPAIR, "control_network": management["id"],
                "control_group": named[fabric.MANAGEMENT_GROUP], "senders_group": named[fabric.SENDERS_GROUP]}

    def _delete(self, stack: str) -> None:
        _held.pop(self._key, None)
        self.get(self._call(DELETE_STACK, name=stack_name(self.slot), stack=stack))
        self._shape = None

    def teardown_slot(self) -> list[tuple[str, str]]:
        stack = self._stacks().get(self.slot)
        if stack is None or str(stack.get("stack_status") or "").startswith("DELETE"):
            return []
        self._delete(stack["id"])
        return [("stack", str(stack["id"]))]

    def reset_slot(self) -> list[tuple[str, str]]:
        return [(stack_name(self.slot), ident) for _, ident in self.teardown_slot()]

    def rebuild_slot(self, kept: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
        return self.reset_slot()

    def play(self, wargame: str) -> None:
        stack = self._stacks().get(self.slot)
        running = _tag(stack, WARGAME_TAG) if stack else ""
        if running and running != wargame:
            raise RangeUnavailable(f"slot {self.slot} runs {running}, not {wargame}; a session opens on a slot "
                                   f"built for its wargame")

    def configure_slot(self) -> list[tuple[str, tuple[str, ...]]]:
        self._shape = None
        baseline = (Path(self.build.source) / BASELINE_RULES).read_text()
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

    def plan_leftovers(self) -> list[tuple[str, str, str]]:
        found = [("stack", str(stack["id"]), f"{stack.get('stack_name')}: a slot beyond the {self.slots} the "
                                              f"cloud settings ask for")
                 for number, stack in sorted(self._stacks().items()) if not 1 <= number <= self.slots]
        servers = self._all(SERVERS, "servers")
        found += [("server", server["id"], f"{server['name']}: the range host or a VM of the range before it")
                  for server in servers if _metadata(server, OLD_HOST)]
        found += [("server", server["id"], f"{server['name']}: an image builder")
                  for server in servers if BUILDS in (server.get("metadata") or {})]
        networks, subnets, _, groups = self._fabric_standing()
        retired = {network["id"] for network in networks if fabric.retired(network)}
        carried = {network["id"] for network in networks if fabric.segment_of(network) and not fabric.retired(network)}
        platform_port = f"{fabric.KEYPAIR}.{fabric.MANAGEMENT}"
        found += [("port", port["id"], f"{port.get('name') or port['id']}: a port the range host left")
                  for port in self._all(PROJECT_PORTS, "ports")
                  if port.get("network_id") in retired
                  or (port.get("network_id") in carried and _detached(port) and port.get("name") != platform_port)]
        found += [("subnet", subnet["id"], f"{subnet.get('name') or subnet['id']}: on a retired network")
                  for subnet in subnets if subnet["network_id"] in retired]
        found += [("network", network["id"], f"{network['name']}: carried a segment no slot carries")
                  for network in networks if network["id"] in retired]
        found += [("group", group["id"], f"{group['name']}: a security group of an earlier range")
                  for group in groups if group["name"] in fabric.RETIRED_GROUPS]
        found += [("image", image["id"], f"{image.get('name')}: a role image of the VM range")
                  for image in self._own_images() if OLD_BUNDLE in image]
        return found

    def clean_leftovers(self) -> list[tuple[str, str]]:
        found = self.plan_leftovers()
        stacks = [(ident, why.split(":", 1)[0]) for kind, ident, why in found if kind == "stack"]
        for ident, name in stacks:
            self.get(self._call(DELETE_STACK, name=name, stack=ident))
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
        return ([("stack", ident) for ident, _ in stacks] + [("server", ident) for ident in sorted(servers)]
                + removed)

    def _until_gone(self, servers: set[str]) -> None:
        deadline = time.monotonic() + GONE_WAIT
        while servers & {server["id"] for server in self._all(SERVERS, "servers")}:
            if time.monotonic() > deadline:
                raise Drifted(f"Nova did not delete {', '.join(sorted(servers))} within {GONE_WAIT}s")
            time.sleep(GONE_POLL)

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
