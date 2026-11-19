import itertools
import stat

import pytest

from range import cloud_config as cloud, declaration, networks, openstack

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
            opened = [{"id": f"rule-{next(self.ids)}", "security_group_id": made["id"], "direction": "egress",
                       "ethertype": ethertype, "protocol": None, "port_range_min": None, "port_range_max": None,
                       "remote_group_id": None, "remote_ip_prefix": None} for ethertype in ("IPv4", "IPv6")]
            self.rules += opened
            return {"security_group": dict(made, security_group_rules=opened)}
        if verb == "POST" and resource == "v2.0/security-group-rules":
            self.rules.append(dict(body["security_group_rule"], id=f"rule-{next(self.ids)}"))
            return {"security_group_rule": self.rules[-1]}
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
                    "security-groups": self.groups, "security-group-rules": self.rules}[kind]
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
        nova="http://nova:8774", project="cr", user="cr",
        ssh_user="ubuntu", ssh_key=str(tmp_path / "ssh" / "id_ed25519"),
    )

@pytest.fixture
def adapter(cloud, tmp_path):
    return openstack.OpenStack(declaration.read(), spec(tmp_path), get=cloud,
                               build=openstack.Build(inside=INSIDE))

@pytest.fixture
def platform(cloud, tmp_path):
    return openstack.OpenStack(declaration.read(), spec(tmp_path), get=cloud,
                               build=openstack.Build(platform="srv-platform", inside=INSIDE))

def network_of(cloud, segment):
    return next(n for n in cloud.networks if f"{networks.TAG}={segment}" in n["tags"])

def test_the_fabric_s_groups_admit_only_ntp_to_the_platform_and_only_the_platform_to_management(cloud, adapter):
    adapter.ensure_fabric()

    groups = {g["name"]: g["id"] for g in cloud.groups}
    assert set(groups) == {networks.EGRESS_GROUP, networks.REACH_GROUP, networks.MANAGEMENT_GROUP, networks.SENDERS_GROUP}
    ingress = [{key: value for key, value in rule.items() if key != "id" and value is not None}
               for rule in cloud.rules if rule["direction"] == "ingress"]
    assert sorted(ingress, key=repr) == sorted([
        {"security_group_id": groups[networks.REACH_GROUP], "direction": "ingress", "ethertype": "IPv4",
         "protocol": "udp", "port_range_min": 123, "port_range_max": 123,
         "remote_group_id": groups[networks.MANAGEMENT_GROUP]},
        {"security_group_id": groups[networks.REACH_GROUP], "direction": "ingress", "ethertype": "IPv4",
         "protocol": "udp", "port_range_min": 5140, "port_range_max": 5140,
         "remote_group_id": groups[networks.SENDERS_GROUP]},
        {"security_group_id": groups[networks.MANAGEMENT_GROUP], "direction": "ingress",
         "ethertype": "IPv4", "remote_group_id": groups[networks.REACH_GROUP]},
    ], key=repr), (
        "a slot node's control port lets in only the platform, and the platform's port takes nothing a "
        "slot starts but NTP, and syslog from the infra nodes alone"
    )


def _egress(cloud, group):
    return sorted(({key: value for key, value in rule.items() if key not in ("id", "security_group_id")
                    and value is not None} for rule in cloud.rules
                   if rule["security_group_id"] == group and rule["direction"] == "egress"), key=repr)

def test_a_slot_node_s_control_port_starts_nothing_but_dhcp_and_traffic_to_the_platform(cloud, adapter):
    adapter.ensure_fabric()

    groups = {g["name"]: g["id"] for g in cloud.groups}
    for name in networks.CONFINED_GROUPS:
        assert _egress(cloud, groups[name]) == sorted([
            {"direction": "egress", "ethertype": "IPv4", "remote_group_id": groups[networks.REACH_GROUP]},
            {"direction": "egress", "ethertype": "IPv4", "protocol": "udp", "port_range_min": 67, "port_range_max": 67},
        ], key=repr), (
            f"{name} holds Neutron's open egress, so a learner's shell reaches the cloud's metadata service "
            f"through the slot node's control port"
        )
    assert _egress(cloud, groups[networks.REACH_GROUP]) == [{"direction": "egress", "ethertype": "IPv4"},
                                                           {"direction": "egress", "ethertype": "IPv6"}]

def test_a_fabric_whose_slot_groups_still_hold_open_egress_is_confined_on_the_next_bring_up(cloud, adapter):
    adapter.ensure_fabric()
    groups = {g["name"]: g["id"] for g in cloud.groups}
    cloud.rules = [rule for rule in cloud.rules
                   if not (rule["direction"] == "egress" and rule["security_group_id"] in
                           {groups[name] for name in networks.CONFINED_GROUPS})]
    cloud.rules += [{"id": f"open-{name}-{ethertype}", "security_group_id": groups[name], "direction": "egress",
                     "ethertype": ethertype, "remote_ip_prefix": "0.0.0.0/0" if ethertype == "IPv4" else None}
                    for name in networks.CONFINED_GROUPS for ethertype in ("IPv4", "IPv6")]

    assert set(adapter.plan_fabric().confine) == set(networks.CONFINED_GROUPS)
    assert not adapter.plan_fabric().clean
    adapter.ensure_fabric()

    assert adapter.plan_fabric().confine == ()
    assert not any(rule["id"].startswith("open-") for rule in cloud.rules)

def test_the_platform_joins_management_through_a_port_in_the_reach_group(cloud, platform):
    platform.ensure_fabric()

    [port] = cloud.ports
    reach = next(g["id"] for g in cloud.groups if g["name"] == networks.REACH_GROUP)
    assert port["network_id"] == network_of(cloud, networks.MANAGEMENT)["id"]
    assert port["security_groups"] == [reach]
    assert port["device_id"] == "srv-platform"

def test_building_on_an_empty_project_makes_the_whole_fabric_with_no_way_out_of_management(cloud, adapter):
    adapter.ensure_fabric()

    tags = sorted(t for n in cloud.networks for t in n["tags"])
    assert tags == [f"{networks.TAG}=mgmt"], (
        "the internet and the estate are each slot's own docker networks on the range host")
    assert len(cloud.subnets) == 1
    assert [k["name"] for k in cloud.keypairs] == [networks.KEYPAIR]
    [mgmt] = [s for s in cloud.subnets if s["network_id"] == network_of(cloud, networks.MANAGEMENT)["id"]]
    assert mgmt["gateway_ip"] is None and mgmt["enable_dhcp"] is True

def test_no_range_subnet_announces_a_dns_resolver_because_the_range_has_no_internet(cloud, adapter):
    adapter.ensure_fabric()

    assert {tuple(s["dns_nameservers"]) for s in cloud.subnets} == {("0.0.0.0",)}

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

def replaced(cloud, tmp_path, old):
    openstack.OpenStack(declaration.read(), spec(tmp_path), get=cloud,
                        build=openstack.Build(platform=old, inside=INSIDE)).ensure_fabric()
    for port in cloud.ports:
        if port["device_id"] == old:
            port.update(device_id="", device_owner="")

def test_a_replaced_platform_takes_over_the_detached_management_port_and_so_its_address(cloud, platform, tmp_path):
    replaced(cloud, tmp_path, "srv-old")
    kept = [dict(p) for p in cloud.ports if p["name"] == f"{networks.KEYPAIR}.{networks.MANAGEMENT}"]
    replaced(cloud, tmp_path, "srv-older")

    platform.ensure_fabric()

    named = [p for p in cloud.ports if p["name"] == f"{networks.KEYPAIR}.{networks.MANAGEMENT}"]
    assert [p["device_id"] for p in named] == ["srv-platform"], (
        "Nova detaches a port it did not create when the server is deleted and leaves it standing; "
        "one left per up --replace kept the management subnet in use and bin/cloud down failed"
    )
    assert [p["id"] for p in named] == [p["id"] for p in kept], (
        "every slot's user data names the collector's address; a new address would make every slot stale")

def test_taking_it_down_removes_detached_ports_that_hold_a_subnet_in_use(cloud, platform, tmp_path):
    replaced(cloud, tmp_path, "srv-old")
    management = network_of(cloud, networks.MANAGEMENT)["id"]
    cloud.ports.append({"id": "port-left", "name": "cr-range.mgmt", "network_id": management,
                        "device_id": "", "device_owner": ""})

    platform.teardown_fabric()

    assert cloud.ports == [] and cloud.subnets == [] and cloud.networks == []

def test_planning_only_reads(cloud, adapter):
    adapter.plan_fabric()

    assert not cloud.writes()
