from __future__ import annotations

import shlex
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dataclasses import dataclass, replace

from range.declared import Declaration
from range.ports import (
    Node, Ran, RangeUnavailable, Segment, Sensor, Shape, execute, reported,
    reporting,
)

TOKEN = "POST {keystone}/v3/auth/tokens"
NETWORKS = "GET {neutron}/v2.0/networks?project_id={project}&tags-any={tags}"
SUBNETS = "GET {neutron}/v2.0/subnets?network_id={network}"
SERVERS = "GET {nova}/servers/detail?project_id={project}"
BOOT = "POST {nova}/servers"

CALLS = (TOKEN, NETWORKS, SUBNETS, SERVERS, BOOT)

FIXED = "OS-EXT-IPS:type"
LAUNCHED = "OS-SRV-USG:launched_at"
PAGE_LIMIT = 50

RENEW_BEFORE = timedelta(seconds=30)
CONNECT_TIMEOUT = 10
SERVER_ALIVE_INTERVAL = 15
SERVER_ALIVE_COUNT_MAX = 3
PINNING = {"stricthostkeychecking true", "stricthostkeychecking ask"}
NOVA_MICROVERSION = "2.1"
SUBJECT_TOKEN = "X-Subject-Token"
SEGMENT_TAG = "fsl.segment.id"
ATTACKER_ROLE = "attacker"

SETTINGS = {
    "keystone": "FSL_OPENSTACK_KEYSTONE",
    "user": "FSL_OPENSTACK_USER",
    "password": "FSL_OPENSTACK_PASSWORD",
    "project": "FSL_OPENSTACK_PROJECT",
    "ssh_user": "FSL_OPENSTACK_SSH_USER",
    "ssh_key": "FSL_OPENSTACK_SSH_KEY",
    "ssh_config": "FSL_OPENSTACK_SSH_CONFIG",
    "region": "FSL_OPENSTACK_REGION",
    "interface": "FSL_OPENSTACK_INTERFACE",
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
    ssh_config: str = "",
    region: str = "RegionOne",
    interface: str = "public",
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
    if ssh_config and not Path(ssh_config).expanduser().is_file():
        raise RangeUnavailable(
            f"{SETTINGS['ssh_config']} names {ssh_config} and there is no such "
            f"file. ssh includes a file that is not there without a word and "
            f"connects as if the deployment had configured nothing"
        )

    known = (keystone, user, password, project, ssh_user, ssh_key,
             ssh_config, region, interface)

    def rediscover() -> tuple[Cloud, object]:
        cloud = discover(
            keystone, user, password, project, ssh_user, ssh_key,
            region=region, interface=interface, ssh_config=ssh_config,
        )
        _connected[known] = (cloud, http_reader(cloud, password))
        return _connected[known]

    cloud, reader = _connected.get(known) or rediscover()
    return OpenStack(declared, cloud, get=reader, rediscover=rediscover)

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
    ssh_config: str = "",
    timeout: float = 30.0,
) -> "Cloud":
    answered = _signed_in(keystone, user, password, project, timeout)

    catalog = (answered.json().get("token") or {}).get("catalog") or []
    return Cloud(
        keystone=keystone,
        neutron=_endpoint(catalog, "network", region, interface),
        nova=_endpoint(catalog, "compute", region, interface),
        project=project,
        user=user,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        ssh_config=ssh_config,
    )

def _signed_in(keystone: str, user: str, password: str, project: str, timeout: float):
    answered = _send(
        "post", f"{keystone}/v3/auth/tokens", None,
        _password_body(user, password, project), timeout,
    )
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

def _password_body(user: str, password: str, project: str) -> dict:
    return {
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

def http_reader(cloud: "Cloud", password: str, timeout: float = 30.0):
    held: dict = {"token": "", "expires": None}

    def authenticate() -> str:
        answered = _signed_in(
            cloud.keystone, cloud.user, password, cloud.project, timeout
        )
        held["token"] = answered.headers.get(SUBJECT_TOKEN, "")
        held["expires"] = _expiry(answered)
        if not held["token"]:
            raise RangeUnavailable(
                f"{cloud.keystone} issued no {SUBJECT_TOKEN}, so nothing can "
                f"be asked of this cloud"
            )
        return held["token"]

    def read(call: str) -> dict:
        url = call.split(" ", 1)[1] if " " in call else call
        token = held["token"]
        if not token or _spent(held["expires"]):
            token = authenticate()
        answered = _send("get", url, token, None, timeout)
        if answered.status_code == 401:
            answered = _send("get", url, authenticate(), None, timeout)
        if not answered.ok:
            refused = EndpointGone if answered.status_code == 404 else RangeUnavailable
            raise refused(
                f"{url} answered {answered.status_code}: "
                f"{answered.text.strip()[:200]}"
            )
        return answered.json()

    return read

def _expiry(answered) -> datetime | None:
    stamp = ((answered.json().get("token") or {}) if answered.content else {}).get(
        "expires_at"
    )
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None

def _spent(expires: datetime | None) -> bool:
    return expires is not None and datetime.now(timezone.utc) + RENEW_BEFORE >= expires

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

def unimplemented(call: str) -> dict:
    raise NotImplementedError(
        f"the sketch issues no cloud call; a real adapter would send {call}, "
        f"authenticated by the first of {CALLS}"
    )


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


class OpenStack:
    def __init__(
        self, declared: Declaration, cloud: Cloud, get=unimplemented, rediscover=None
    ):
        self.declared = declared
        self.cloud = cloud
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
        wanted = ",".join(
            f"{SEGMENT_TAG}={segment.id}" for segment in self.declared.segments
        )
        bound = self._bind(self._all(NETWORKS, "networks", tags=wanted))
        servers = self._all(SERVERS, "servers")
        self._generations = _generations(servers)

        segments = []
        for declared in self.declared.segments:
            network = bound.get(declared.id)
            if network is None:
                raise RangeUnavailable(
                    f"the declaration names the segment {declared.id!r} and no "
                    f"network of project {self.cloud.project!r} is tagged "
                    f"{SEGMENT_TAG}={declared.id}"
                )
            allocated = self._all(SUBNETS, "subnets", network=network["id"])
            bound_subnet = _one_ipv4_subnet(declared.id, allocated)
            segments.append(
                replace(
                    declared,
                    subnet=bound_subnet.get("cidr", ""),
                    network=network["id"],
                    gateway=bound_subnet.get("gateway_ip", ""),
                    nodes=self._nodes(network["name"], servers),
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
                command = self._ssh(address, stdin is not None, said, config)
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
        ]
        written.write_text("\n".join(included + defaults) + "\n")
        generation = self._generations.get(address)
        if generation and not self._deployment_checks_keys(written, address):
            aliased = [f"Host {address}", f"  HostKeyAlias {generation}"]
            written.write_text("\n".join(included + aliased + defaults) + "\n")
        return written

    def _deployment_checks_keys(self, config: Path, address: str) -> bool:
        try:
            resolved = subprocess.run(
                ["ssh", "-G", "-F", str(config), f"{self.cloud.ssh_user}@{address}"],
                capture_output=True, text=True, errors="replace",
                timeout=CONNECT_TIMEOUT,
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RangeUnavailable(
                f"could not read how ssh would reach {address}: {exc}"
            ) from exc
        return bool(PINNING & set(resolved)) or any(
            line.startswith("hostkeyalias ") for line in resolved
        )

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
            return self.runner(ATTACKER_ROLE, segment_id)(argv, timeout=timeout)

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

    def _nodes(self, network_name: str, servers: list[dict]) -> tuple[Node, ...]:
        found = [
            Node(name=server["name"], address=entry["addr"])
            for server in servers
            for entry in (server.get("addresses") or {}).get(network_name, [])
            if entry.get(FIXED) == "fixed" and entry.get("version", 4) == 4
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
        for segment in self.describe().segments:
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
