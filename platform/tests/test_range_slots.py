import base64
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from range import fabric, opnsense, slot
from range.ports import RangeUnavailable
from tests.test_openstack_slot import (
    DECLARED, INSIDE, SPEC, WARGAME_HOST, Cloud, build, edge_declaration,
)

from range import openstack

PLATFORM = {"id": "srv-platform", "name": "fsl-platform", "status": "ACTIVE",
            "metadata": {}, "addresses": {"fsl-mgmt": [
                {"addr": "10.31.0.195", "OS-EXT-IPS:type": "fixed", "version": 4}]}}


class TwoSlots(Cloud):
    def __init__(self):
        super().__init__()
        for want in fabric.wanted(self.decl, INSIDE, 2):
            net_id = f"net-{want.carrier}"
            if not any(n["id"] == net_id for n in self.networks):
                self.networks.append({"id": net_id, "name": fabric.network_name(want.segment, 2),
                                      "tags": fabric.network_tags(want.segment, 2)})
            self.subnets.append({
                "id": f"sub-{want.name}", "network_id": net_id, "name": want.name,
                "cidr": want.cidr, "enable_dhcp": want.dhcp,
                "gateway_ip": want.cidr.replace("0/24", "1") if want.gateway else None,
            })
        self.servers.append(dict(PLATFORM))

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if verb == "GET" and parts.path.strip("/") == "v2.0/subnets" and "network_id" in query:
            self.calls.append((verb, parts.path.strip("/"), body))
            return {"subnets": [s for s in self.subnets if s["network_id"] == query["network_id"][0]]}
        return super().__call__(call, body)

    def settle(self):
        names = {n["id"]: n["name"] for n in self.networks}
        for server in self.servers:
            if server["id"] == PLATFORM["id"]:
                continue
            server["status"] = "ACTIVE"
            server["addresses"] = {}
            for wired in server.get("networks") or []:
                port = next(p for p in self.ports if p["id"] == wired["port"])
                server["addresses"].setdefault(names[port["network_id"]], []).extend(
                    {"addr": f["ip_address"], "OS-EXT-IPS:type": "fixed", "version": 4}
                    for f in port["fixed_ips"])

    def server(self, name):
        return next(s for s in self.servers if s["name"] == name)


def range_of(cloud, slots=2):
    from dataclasses import replace
    return openstack.OpenStack(DECLARED, SPEC, get=cloud, build=replace(build(), slots=slots))


@pytest.fixture
def two():
    cloud = TwoSlots()
    adapter = range_of(cloud)
    for one in adapter.every_slot():
        one.ensure_slot()
    cloud.settle()
    return cloud, adapter


def test_a_two_slot_range_takes_two_sessions_at_once():
    adapter = range_of(TwoSlots())

    assert adapter.max_sessions == 2
    assert [one.slot for one in adapter.every_slot()] == [1, 2]
    with pytest.raises(RangeUnavailable, match="slot 3"):
        adapter.in_slot(3)


def test_the_second_slot_boots_its_own_copy_of_every_host_under_its_own_names(two):
    cloud, _ = two

    for host in DECLARED.hosts:
        first, second = cloud.server(host), cloud.server(f"{host}-2")
        assert first["metadata"] == {slot.HOST: host}, "slot 1 keeps today's names and metadata"
        assert second["metadata"] == {slot.HOST: host, slot.SLOT: "2"}
        assert {p["name"] for p in cloud.ports if p["id"] in {w["port"] for w in second["networks"]}} == {
            f"{host}-2.{segment}" for segment in DECLARED.hosts[host].segments}


def test_each_slot_stands_on_its_own_internet_and_estate_and_shares_management(two):
    cloud, _ = two
    network = {n["id"]: n["name"] for n in cloud.networks}

    for host, entry in DECLARED.hosts.items():
        for segment in entry.segments:
            first = cloud.port(f"{host}.{segment}")
            second = cloud.port(f"{host}-2.{segment}")
            if segment == fabric.MANAGEMENT:
                assert first["network_id"] == second["network_id"]
                assert first["fixed_ips"] != second["fixed_ips"]
            else:
                assert network[second["network_id"]] == fabric.network_name(segment, 2)
                assert first["network_id"] != second["network_id"]


def test_each_slot_s_edge_holds_the_same_origin_gateways_and_its_attacker_the_same_origin_addresses():
    decl = edge_declaration()
    networks, subnets = [], []
    for number in (1, 2):
        for want in fabric.wanted(decl, INSIDE, number):
            net_id = f"net-{want.carrier}"
            if not any(n["id"] == net_id for n in networks):
                networks.append({"id": net_id, "name": fabric.network_name(want.segment, number),
                                 "tags": fabric.network_tags(want.segment, number)})
            subnets.append({"id": f"sub-{want.name}", "network_id": net_id, "cidr": want.cidr,
                            "gateway_ip": want.cidr.replace("0/24", "1") if want.gateway else None})
    ready = {host: f"img-{host}" for host in decl.hosts}

    first, second = (slot.plan(decl, networks, subnets, [], [], ready, number) for number in (1, 2))

    def held(plan, name):
        port = next(p for p in plan.ports if p.name == name)
        return sorted(address for _, address in port.fixed_ips), {subnet for subnet, _ in port.fixed_ips}

    for host, segment in (("fsl-pf", "ru"), ("fsl-pf", "estate"), ("fsl-kali", "ru")):
        one, other = held(first, f"{host}.{segment}"), held(second, f"{host}-2.{segment}")
        assert one[0] == other[0] and one[0], (
            "an alert's source address is binned to its country by the origin subnets; a second "
            "slot on other addresses would place its attacks somewhere else on the map"
        )
        assert one[1] != other[1], "each slot's copy sits on its own slot's subnet"


def test_a_slot_s_hosts_learn_their_own_slot_s_estate_addresses(two):
    cloud, _ = two
    wargames = cloud.port(f"{WARGAME_HOST}-2.estate")["fixed_ips"][0]["ip_address"]
    config = yaml.safe_load(base64.b64decode(cloud.server("fsl-waf-2")["user_data"]).decode())
    [hosts] = [f for f in config["write_files"] if f["path"] == "/etc/hosts"]

    assert f"{wargames} {' '.join(DECLARED.hosts[WARGAME_HOST].names)}\n" in hosts["content"]
    assert cloud.port(f"{WARGAME_HOST}.estate")["network_id"] != cloud.port(f"{WARGAME_HOST}-2.estate")["network_id"]


def test_a_slot_reads_its_own_hosts_by_their_declared_names(two):
    cloud, adapter = two
    shape = adapter.in_slot(2).describe()
    mgmt = next(s for s in shape.segments if s.id == fabric.MANAGEMENT)
    estate = next(s for s in shape.segments if s.id == "estate")

    assert {node.name for node in mgmt.nodes} == set(DECLARED.hosts) | {"fsl-platform"}
    assert {node.address for node in estate.nodes} == {
        cloud.port(f"{host}-2.estate")["fixed_ips"][0]["ip_address"]
        for host, entry in DECLARED.hosts.items() if "estate" in entry.segments
    }
    assert estate.network == "net-estate-2"


def test_a_slot_runs_a_role_s_command_on_its_own_host(two):
    cloud, adapter = two

    first = adapter.in_slot(1).address("gateway")
    second = adapter.in_slot(2).address("gateway")

    assert first == cloud.port("fsl-waf.mgmt")["fixed_ips"][0]["ip_address"]
    assert second == cloud.port("fsl-waf-2.mgmt")["fixed_ips"][0]["ip_address"]
    assert adapter.in_slot(2).address("scorer") == "10.31.0.195", "the collector is shared"


def test_closing_one_slot_rebuilds_only_its_own_vms(two):
    cloud, adapter = two

    rebuilt = adapter.in_slot(2).reset_slot()

    ids = {server for _, server in rebuilt}
    assert ids and ids <= {s["id"] for s in cloud.servers if slot.slot_of(s) == 2 and slot.in_slot(s)}


def test_taking_one_slot_down_leaves_the_other_standing(two):
    cloud, adapter = two

    adapter.in_slot(2).teardown_slot()

    assert {s["name"] for s in cloud.servers} == set(DECLARED.hosts) | {"fsl-platform"}
    assert all(not p["name"].split(".")[0].endswith("-2") for p in cloud.ports)
    assert adapter.in_slot(1).plan_slot().clean


def test_the_second_slot_s_edge_names_itself_so_the_collector_can_tell_its_logs_apart():
    wanted = {"key": "ssh-ed25519 AAAA", "mtu": 1450, "hostname": "edge-2"}
    template = (openstack.Path(build().source) / opnsense.CONFIG).read_text()

    assert "<hostname>edge-2</hostname>" in opnsense.render(template, wanted)
    assert f"<hostname>{opnsense.HOSTNAME}</hostname>" in opnsense.render(template, {"key": "k", "mtu": 1450}), (
        "slot 1's rendered config stays byte for byte what its edge recorded, so its in-place "
        "reset still matches"
    )


def test_opening_the_collector_for_one_slot_keeps_the_other_slot_s_senders(two):
    from dataclasses import replace
    cloud, adapter = two
    adapter.declared = replace(DECLARED, roles={**DECLARED.roles, "edge": "fsl-waf"}, watches={})
    rules = []
    group = {"id": "sg-reach", "name": fabric.REACH_GROUP, "security_group_rules": rules}
    cloud.groups = [g for g in cloud.groups if g["name"] != fabric.REACH_GROUP] + [group]
    original = cloud.__call__

    def hearing(call, body=None):
        verb, url = call.split(" ", 1)
        if verb == "POST" and "security-group-rules" in url:
            rules.append(dict(body["security_group_rule"], id=f"rule-{len(rules)}"))
            return {}
        if verb == "DELETE" and "security-group-rules" in url:
            rules[:] = [r for r in rules if r["id"] != url.rsplit("/", 1)[1]]
            return {}
        return original(call, body)

    adapter.get = hearing
    for one in adapter.every_slot():
        one.open_collector()
    adapter.in_slot(1).open_collector()

    heard = {r["remote_ip_prefix"] for r in rules}
    assert heard == {f"{cloud.port(name)['fixed_ips'][0]['ip_address']}/32"
                     for name in ("fsl-waf.mgmt", "fsl-waf-2.mgmt")}, (
        "each slot opened the collector for its own senders; the second must not have deleted "
        "the first's rule, or the first slot's alerts stop arriving"
    )


def test_a_standing_two_slot_fabric_is_clean_and_a_third_slot_s_network_is_a_leftover():
    cloud = TwoSlots()
    networks = cloud.networks + [{"id": "net-internet-3", "name": "fsl-internet-3",
                                  "tags": fabric.network_tags("internet", 3)}]
    keys = [{"name": fabric.KEYPAIR, "public_key": "ssh-ed25519 AAAA"}]

    plan = fabric.plan(DECLARED, networks, cloud.subnets, keys, "ssh-ed25519 AAAA",
                       cloud.groups, inside=INSIDE, slots=2)

    assert plan.networks == () and plan.subnets == () and plan.drifted == ()
    assert any("fsl-internet-3" in reason for reason in plan.leftovers)


def test_ensuring_a_two_slot_fabric_tags_the_second_slot_s_networks_with_their_slot():
    made, tagged = [], {}

    def neutron(call, body=None):
        verb, url = call.split(" ", 1)
        path = urlsplit(url).path.strip("/")
        if verb == "GET":
            return {"networks": [], "subnets": [], "keypairs": [], "security_groups": [],
                    "ports": []}
        if path == "v2.0/networks":
            made.append(body["network"]["name"])
            return {"network": {"id": f"id-{body['network']['name']}"}}
        if path.endswith("/tags"):
            tagged[path.split("/")[2]] = body["tags"]
            return {}
        if path == "v2.0/security-groups":
            return {"security_group": {"id": f"sg-{body['security_group']['name']}"}}
        return {}

    adapter = openstack.OpenStack(DECLARED, SPEC, get=neutron,
                                  build=openstack.Build(inside=INSIDE, slots=2))
    adapter._public_key = lambda make=False: "ssh-ed25519 AAAA"
    adapter.ensure_fabric()

    assert made == ["fsl-internet", "fsl-estate", "fsl-mgmt", "fsl-internet-2", "fsl-estate-2"]
    assert tagged["id-fsl-internet-2"] == [f"{fabric.TAG}=internet", f"{fabric.SLOT_TAG}=2"]
    assert tagged["id-fsl-internet"] == [f"{fabric.TAG}=internet"]
