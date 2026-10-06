import base64
import ipaddress
import itertools
import pathlib
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from range import declared, fabric, images, openstack, slot
from range.ports import Drifted

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()

class Cloud:
    def __init__(self, decl=DECLARED, source=ROOT):
        self.decl = decl
        self.ids = itertools.count(1)
        self.networks, self.subnets = [], []
        for want in fabric.wanted(decl):
            net_id = f"net-{want.segment}"
            if not any(n["id"] == net_id for n in self.networks):
                self.networks.append({"id": net_id, "name": f"fsl-{want.segment}",
                                      "tags": [f"{fabric.TAG}={want.segment}"]})
            self.subnets.append({
                "id": f"sub-{want.name}", "network_id": net_id, "name": want.name,
                "cidr": want.cidr, "enable_dhcp": want.dhcp,
                "gateway_ip": want.cidr.replace("0/24", "1") if want.gateway else None,
            })
        self.groups = [{"id": "sg-range", "name": fabric.RANGE_GROUP},
                       {"id": "sg-reach", "name": fabric.REACH_GROUP}]
        self.images = [{"id": "img-ubuntu", "name": "ubuntu-24.04", "status": "active"}]
        for host, entry in decl.hosts.items():
            if entry.image:
                self.images.append({"id": f"img-{host}", "name": entry.image, "status": "active"})
                continue
            digest = images.bundle(source, host, entry.setup, entry.files).digest
            self.images.append({"id": f"img-{host}", "name": host, "status": "active",
                                images.BUNDLE: digest})
        self.ports, self.servers, self.calls = [], [], []

    def allocate(self, network_id):
        on_net = [s for s in self.subnets if s["network_id"] == network_id]
        subnet = next((s for s in on_net if s["enable_dhcp"]), on_net[0])
        taken = {f["ip_address"] for p in self.ports for f in p["fixed_ips"]}
        hosts = ipaddress.ip_network(subnet["cidr"]).hosts()
        free = next(str(a) for a in itertools.islice(hosts, 10, None) if str(a) not in taken)
        return [{"subnet_id": subnet["id"], "ip_address": free}]

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        parts = urlsplit(url)
        path, query = parts.path.strip("/"), parse_qs(parts.query)
        self.calls.append((verb, path, body))
        if verb == "GET":
            found = {
                "v2.0/networks": lambda: {"networks": self.networks},
                "v2.0/subnets": lambda: {"subnets": self.subnets},
                "v2.0/security-groups": lambda: {"security_groups": self.groups},
                "v2.0/ports": lambda: {"ports": [
                    p for p in self.ports if p["network_id"] == query["network_id"][0]]},
                "v2.1/os-keypairs": lambda: {"keypairs": []},
                "v2.1/servers/detail": lambda: {"servers": self.servers},
                "v2.1/flavors": lambda: {"flavors": [{"id": "f-2", "name": "m1.small"}]},
                "v2/images": lambda: {"images": [
                    i for i in self.images if i["name"] == query["name"][0]]},
            }
            return found[path]()
        if verb == "POST" and path == "v2.0/ports":
            port = dict(body["port"], id=f"port-{next(self.ids)}",
                        mac_address=f"fa:16:3e:00:00:{len(self.ports):02x}")
            port["fixed_ips"] = [
                {"subnet_id": f["subnet_id"], "ip_address": f["ip_address"]}
                for f in body["port"].get("fixed_ips") or []
            ] or self.allocate(port["network_id"])
            self.ports.append(port)
            return {"port": port}
        if verb == "POST" and path == "v2.1/servers":
            server = dict(body["server"], id=f"srv-{next(self.ids)}", status="BUILD", addresses={})
            self.servers.append(server)
            return {"server": {"id": server["id"]}}
        if verb == "POST" and path.endswith("/action"):
            server = next(s for s in self.servers if s["id"] == path.rsplit("/", 2)[-2])
            if "rebuild" in (body or {}):
                server["imageRef"] = body["rebuild"]["imageRef"]
            return {}
        if verb == "DELETE":
            kind, ident = path.rsplit("/", 2)[-2:]
            pool = {"servers": self.servers, "ports": self.ports}[kind]
            pool[:] = [r for r in pool if r["id"] != ident]
            return {}
        raise AssertionError(call)

    def booted(self, host):
        return next(s for s in self.servers if s["metadata"][slot.HOST] == host)

    def config(self, host):
        return yaml.safe_load(base64.b64decode(self.booted(host)["user_data"]).decode())

    def port(self, name):
        return next(p for p in self.ports if p["name"] == name)

SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="fsl",
    user="fsl", ssh_user="ubuntu", ssh_key="/keys/fsl",
)

@pytest.fixture
def cloud():
    return Cloud()

def adapter(cloud, decl=DECLARED):
    build = openstack.Build(source=str(ROOT), base_image="ubuntu-24.04", flavor="m1.small",
                            network="net-platform", platform="srv-platform")
    return openstack.OpenStack(decl, SPEC, get=cloud, build=build)

def edge_declaration():
    from range.declared import Declaration, Host, Origin, Segment

    return Declaration(
        segments=(
            Segment(id="ru", name="Internet", origin="Russia"),
            Segment(id="estate", name="Estate"),
            Segment(id="mgmt", name="Management"),
        ),
        origins=(Origin(id="ru", label="Russia",
                        subnet="5.188.10.0/24", addresses=1, segment="ru"),),
        roles={"edge": "fsl-pf", "gateway": "fsl-waf", "attacker": "fsl-kali",
               "sensor": "fsl-pf", "scorer": "fsl-platform", "target": "fsl-shop"},
        watches={"sensor": "edge"},
        hosts={
            "fsl-pf": Host(image="pf-base", segments=("ru", "estate", "mgmt")),
            "fsl-waf": Host(setup="waf/setup.sh", files=("waf",), segments=("estate", "mgmt")),
            "fsl-kali": Host(setup="waf/setup.sh", files=("waf",), segments=("ru", "mgmt")),
        },
        default_origin="ru",
    )

def test_the_prebuilt_edge_boots_from_its_image_with_no_cloud_init(tmp_path):
    (tmp_path / "waf").mkdir()
    (tmp_path / "waf" / "setup.sh").write_text("set -eu\n")
    decl = edge_declaration()
    cloud = Cloud(decl, source=tmp_path)
    build = openstack.Build(source=str(tmp_path), base_image="ubuntu-24.04",
                            flavor="m1.small", network="net-platform", platform="srv-platform")

    openstack.OpenStack(decl, SPEC, get=cloud, build=build).ensure_slot()

    pf = cloud.booted("fsl-pf")
    assert pf["imageRef"] == "img-fsl-pf"
    assert "user_data" not in pf or not pf["user_data"], (
        "pfSense is FreeBSD and runs no cloud-init; a Linux cloud-config would "
        "be ignored at best and the platform configures it over ssh instead"
    )
    assert cloud.booted("fsl-waf")["user_data"], "the Linux hosts still learn names"

def test_the_edge_forwarding_ports_may_carry_any_source_so_it_can_route_un_natted(tmp_path):
    (tmp_path / "waf").mkdir()
    (tmp_path / "waf" / "setup.sh").write_text("set -eu\n")
    decl = edge_declaration()
    cloud = Cloud(decl, source=tmp_path)
    build = openstack.Build(source=str(tmp_path), base_image="ubuntu-24.04",
                            flavor="m1.small", network="net-platform", platform="srv-platform")

    openstack.OpenStack(decl, SPEC, get=cloud, build=build).ensure_slot()

    pairs = {"0.0.0.0/0"}
    for segment in ("ru", "estate"):
        port = cloud.port(f"fsl-pf.{segment}")
        assert {p["ip_address"] for p in port.get("allowed_address_pairs") or []} == pairs, (
            f"the edge routes packets whose source is not its own on {segment}; "
            f"Neutron anti-spoofing drops those without an address pair"
        )
    mgmt = cloud.port("fsl-pf.mgmt")
    assert not mgmt.get("allowed_address_pairs"), (
        "management carries no forwarded traffic, so it keeps strict anti-spoofing"
    )
    assert not cloud.port("fsl-waf.estate").get("allowed_address_pairs"), (
        "a backend host sends only as itself"
    )

def test_every_host_boots_from_its_own_image_on_its_own_ports(cloud):
    adapter(cloud).ensure_slot()

    assert {s["name"] for s in cloud.servers} == set(DECLARED.hosts)
    for host, entry in DECLARED.hosts.items():
        server = cloud.booted(host)
        assert server["imageRef"] == f"img-{host}" and server["flavorRef"] == "f-2"
        assert server["networks"] == [
            {"port": cloud.port(f"{host}.{segment}")["id"]} for segment in entry.segments
        ]
        assert server["config_drive"] is True, (
            "without a config drive the guest DHCPs only its first NIC; on the "
            "gateway that is the Internet, where DHCP is off, and it never "
            "reaches the metadata service"
        )
        assert server["key_name"] == fabric.KEYPAIR

def test_every_range_port_is_in_the_range_group(cloud):
    adapter(cloud).ensure_slot()

    assert {tuple(p["security_groups"]) for p in cloud.ports} == {("sg-range",)}

def test_every_host_is_told_where_the_others_are_on_the_estate(cloud):
    adapter(cloud).ensure_slot()

    board = cloud.port("fsl-wg-board.estate")["fixed_ips"][0]["ip_address"]
    for host in DECLARED.hosts:
        [written] = [f for f in cloud.config(host)["write_files"] if f["path"] == "/etc/hosts"]
        assert f"{board} board board-db\n" in written["content"]

def test_the_gateway_adds_every_origin_gateway_to_its_internet_nic(cloud):
    adapter(cloud).ensure_slot()

    gateway = DECLARED.roles["gateway"]
    port = cloud.port(f"{gateway}.internet")
    script = cloud.config(gateway)["bootcmd"][0][-1]
    assert port["mac_address"] in script
    for origin in DECLARED.origins:
        assert f"{origin.subnet.replace('0/24', '1')}/24" in script

def test_a_slot_standing_writes_nothing_the_second_time(cloud):
    adapter(cloud).ensure_slot()
    written = [c for c in cloud.calls if c[0] != "GET"]

    plan = adapter(cloud).ensure_slot()

    assert [c for c in cloud.calls if c[0] != "GET"] == written
    assert plan.clean and len(plan.standing) == len(DECLARED.hosts)

def test_a_slot_whose_images_are_not_ready_is_refused_before_anything_is_written(cloud):
    cloud.images = [i for i in cloud.images if i["name"] != "fsl-wg-board"]

    with pytest.raises(Drifted, match="fsl-wg-board"):
        adapter(cloud).ensure_slot()
    assert [c for c in cloud.calls if c[0] != "GET"] == []

def test_rebuilding_the_slot_resets_every_vm_to_its_golden_image(cloud):
    adapter(cloud).ensure_slot()
    for server in cloud.servers:
        server["imageRef"] = "img-stale"

    rebuilt = adapter(cloud).rebuild_slot()

    assert {host for host, _ in rebuilt} == set(DECLARED.hosts)
    for host in DECLARED.hosts:
        assert cloud.booted(host)["imageRef"] == f"img-{host}", (
            "Stop resets the slot: Nova rebuild reinstalls each VM from its "
            "golden image, so the next session inherits no solved flags, no "
            "edited rules and no planted data"
        )
    actions = [body for verb, path, body in cloud.calls
               if verb == "POST" and path.endswith("/action")]
    assert len(actions) == len(DECLARED.hosts)
    assert all("rebuild" in a and a["rebuild"]["imageRef"] for a in actions)

def test_a_slot_not_fully_standing_is_not_rebuilt(cloud):
    adapter(cloud).ensure_slot()
    cloud.servers.pop()

    with pytest.raises(Drifted):
        adapter(cloud).rebuild_slot()

    assert [c for c in cloud.calls if c[0] == "POST" and c[1].endswith("/action")] == []

def test_a_standing_host_whose_image_vanished_is_refused_before_any_rebuild(cloud):
    adapter(cloud).ensure_slot()
    cloud.images = [i for i in cloud.images if i["name"] != "fsl-wg-board"]

    with pytest.raises(Drifted, match="fsl-wg-board"):
        adapter(cloud).rebuild_slot()

    assert [c for c in cloud.calls if c[0] == "POST" and c[1].endswith("/action")] == [], (
        "a rebuild that found one image missing only after wiping the others "
        "would leave a half-reset slot; refuse before issuing any rebuild"
    )

def test_taking_the_slot_down_removes_its_servers_and_the_ports_it_made(cloud):
    adapter(cloud).ensure_slot()
    cloud.ports.append({"id": "port-platform", "name": "fsl-platform.mgmt",
                        "network_id": "net-mgmt", "fixed_ips": []})

    removed = adapter(cloud).teardown_slot()

    assert cloud.servers == []
    assert [p["id"] for p in cloud.ports] == ["port-platform"]
    assert {kind for kind, _ in removed} == {"server", "port"}

def test_every_slot_call_is_one_the_api_reference_names():
    reference = {
        openstack.CREATE_PORT: "https://docs.openstack.org/api-ref/network/v2/#create-port",
        openstack.DELETE_PORT: "https://docs.openstack.org/api-ref/network/v2/#delete-port",
        openstack.ATTACH: "https://docs.openstack.org/api-ref/compute/#create-interface",
        openstack.SECURITY_GROUPS: "https://docs.openstack.org/api-ref/network/v2/#list-security-groups",
        openstack.CREATE_RULE: "https://docs.openstack.org/api-ref/network/v2/#create-security-group-rule",
        openstack.ACTION: "https://docs.openstack.org/api-ref/compute/#rebuild-server-rebuild-action",
    }
    source = pathlib.Path(openstack.__file__).read_text()

    for call in reference:
        assert call in source, reference[call]
    for field in ('"fixed_ips"', '"mac_address"', '"security_groups"', '"key_name"',
                  '"interfaceAttachment"', '"port_id"', '"device_id"', '"direction"',
                  '"rebuild"', '"imageRef"'):
        assert field in source, f"{field} is read or sent and checked against {reference}"
