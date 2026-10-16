import itertools
import stat

import pytest

from range import cloud, declared, fabric, openstack

INSIDE = cloud.read(cloud.EXAMPLE).inside

class Neutron:
    def __init__(self):
        self.networks, self.subnets, self.keypairs, self.ports = [], [], [], []
        self.groups, self.rules = [], []
        self.calls = []
        self.ids = itertools.count(1)

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        path = url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((verb, path))
        resource = path.split("?", 1)[0]
        if verb == "GET":
            if resource == "v2.0/networks":
                return {"networks": self.networks}
            if resource == "v2.0/subnets":
                return {"subnets": self.subnets}
            if resource == "v2.0/ports":
                network = path.rsplit("=", 1)[1]
                return {"ports": [p for p in self.ports if p["network_id"] == network]}
            if resource == "os-keypairs":
                return {"keypairs": [{"keypair": k} for k in self.keypairs]}
            if resource == "v2.0/security-groups":
                return {"security_groups": [
                    dict(group, security_group_rules=[
                        rule for rule in self.rules if rule["security_group_id"] == group["id"]])
                    for group in self.groups
                ]}
        if verb == "POST" and resource == "v2.0/networks":
            created = dict(body["network"], id=f"net-{next(self.ids)}", tags=[])
            self.networks.append(created)
            return {"network": created}
        if verb == "PUT" and resource.endswith("/tags"):
            network = next(n for n in self.networks if n["id"] == resource.split("/")[2])
            network["tags"] = list(body["tags"])
            return {"tags": network["tags"]}
        if verb == "POST" and resource == "v2.0/subnets":
            made = [dict(s, id=f"sub-{next(self.ids)}") for s in body["subnets"]]
            for subnet in made:
                subnet.setdefault("gateway_ip", subnet["cidr"].replace("0/24", "1"))
            self.subnets += made
            return {"subnets": made}
        if verb == "POST" and resource == "v2.0/security-groups":
            made = dict(body["security_group"], id=f"sg-{next(self.ids)}")
            self.groups.append(made)
            return {"security_group": made}
        if verb == "POST" and resource == "v2.0/security-group-rules":
            self.rules.append(dict(body["security_group_rule"]))
            return {"security_group_rule": body["security_group_rule"]}
        if verb == "POST" and resource == "v2.0/ports":
            made = dict(body["port"], id=f"port-{next(self.ids)}", device_id="", device_owner="")
            self.ports.append(made)
            return {"port": made}
        if verb == "POST" and resource.endswith("/os-interface"):
            port = next(p for p in self.ports if p["id"] == body["interfaceAttachment"]["port_id"])
            port.update(device_id=resource.split("/")[1], device_owner="compute:nova")
            return {"interfaceAttachment": body["interfaceAttachment"]}
        if verb == "POST" and resource == "os-keypairs":
            self.keypairs.append(dict(body["keypair"]))
            return {"keypair": body["keypair"]}
        if verb == "DELETE":
            kind, ident = resource.rsplit("/", 2)[-2:]
            pool = {"networks": self.networks, "subnets": self.subnets,
                    "os-keypairs": self.keypairs, "ports": self.ports,
                    "security-groups": self.groups}[kind]
            pool[:] = [r for r in pool if r.get("id", r.get("name")) != ident]
            return {}
        raise AssertionError(call)

    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

@pytest.fixture
def cloud():
    return Neutron()

def spec(tmp_path):
    return openstack.Cloud(
        keystone="http://keystone:5000", neutron="http://neutron:9696",
        nova="http://nova:8774", project="fsl", user="fsl",
        ssh_user="ubuntu", ssh_key=str(tmp_path / "ssh" / "id_ed25519"),
    )

@pytest.fixture
def adapter(cloud, tmp_path):
    return openstack.OpenStack(declared.read(), spec(tmp_path), get=cloud,
                               build=openstack.Build(inside=INSIDE))

@pytest.fixture
def platform(cloud, tmp_path):
    return openstack.OpenStack(declared.read(), spec(tmp_path), get=cloud,
                               build=openstack.Build(platform="srv-platform", inside=INSIDE))

def network_of(cloud, segment):
    return next(n for n in cloud.networks if f"{fabric.TAG}={segment}" in n["tags"])

def test_the_fabric_s_groups_admit_only_ntp_to_the_platform_and_only_the_platform_to_management(cloud, adapter):
    adapter.ensure_fabric()

    groups = {g["name"]: g["id"] for g in cloud.groups}
    assert set(groups) == {fabric.RANGE_GROUP, fabric.REACH_GROUP, fabric.MANAGEMENT_GROUP}
    assert sorted(cloud.rules, key=repr) == sorted([
        {"security_group_id": groups[fabric.RANGE_GROUP], "direction": "ingress", "ethertype": "IPv4"},
        {"security_group_id": groups[fabric.REACH_GROUP], "direction": "ingress", "ethertype": "IPv4",
         "protocol": "udp", "port_range_min": 123, "port_range_max": 123,
         "remote_group_id": groups[fabric.MANAGEMENT_GROUP]},
        {"security_group_id": groups[fabric.MANAGEMENT_GROUP], "direction": "ingress",
         "ethertype": "IPv4", "remote_group_id": groups[fabric.REACH_GROUP]},
    ], key=repr), (
        "the attacker has a port on management too; a management port that "
        "lets in any range host lets Kali reach the edge's web GUI and the "
        "wargame host's published ports without crossing the edge or the WAF, "
        "and the platform's port takes nothing a range host starts but NTP"
    )

def test_the_platform_joins_management_through_a_port_in_the_reach_group(cloud, platform):
    platform.ensure_fabric()

    [port] = cloud.ports
    reach = next(g["id"] for g in cloud.groups if g["name"] == fabric.REACH_GROUP)
    assert port["network_id"] == network_of(cloud, fabric.MANAGEMENT)["id"]
    assert port["security_groups"] == [reach]
    assert port["device_id"] == "srv-platform"

def test_building_on_an_empty_project_makes_the_whole_fabric_with_no_way_out_of_management(cloud, adapter):
    adapter.ensure_fabric()

    tags = sorted(t for n in cloud.networks for t in n["tags"])
    assert tags == [f"{fabric.TAG}={s}" for s in ("estate", "internet", "mgmt")]
    assert len(cloud.subnets) == 32
    assert [k["name"] for k in cloud.keypairs] == [fabric.KEYPAIR]
    [mgmt] = [s for s in cloud.subnets if s["network_id"] == network_of(cloud, fabric.MANAGEMENT)["id"]]
    assert mgmt["gateway_ip"] is None and mgmt["enable_dhcp"] is True

def test_the_platform_makes_its_own_key_and_keeps_it_private(cloud, adapter, tmp_path):
    adapter.ensure_fabric()

    private = tmp_path / "ssh" / "id_ed25519"
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert cloud.keypairs[0]["public_key"].split()[:2] == (
        private.with_name("id_ed25519.pub").read_text().split()[:2]
    )

def test_building_twice_only_reads_the_second_time(cloud, platform):
    platform.ensure_fabric()
    written = len(cloud.writes())

    plan = platform.ensure_fabric()

    assert len(cloud.writes()) == written and not plan.reach

def test_taking_it_down_removes_only_what_the_fabric_owns(cloud, platform):
    cloud.networks.append({"id": "net-scratch", "name": "tenant-scratch", "tags": []})
    platform.ensure_fabric()
    platform.teardown_fabric()

    assert [n["id"] for n in cloud.networks] == ["net-scratch"]
    assert cloud.ports == [] and cloud.subnets == [] and cloud.keypairs == [] and cloud.groups == []

def test_planning_only_reads(cloud, adapter):
    adapter.plan_fabric()

    assert not cloud.writes()
