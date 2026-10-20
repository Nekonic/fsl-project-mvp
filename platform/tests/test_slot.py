import base64
import pathlib

import pytest
import yaml

from range import cloud, declared, fabric, slot

INSIDE = cloud.read(cloud.EXAMPLE).inside

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
READY = {host: f"img-{host}" for host in DECLARED.hosts}

def fabric_standing():
    networks, subnets = [], []
    for want in fabric.wanted(DECLARED, INSIDE):
        net_id = f"net-{want.segment}"
        if not any(n["id"] == net_id for n in networks):
            networks.append({"id": net_id, "name": f"fsl-{want.segment}",
                             "tags": [f"{fabric.TAG}={want.segment}"]})
        subnets.append({"id": f"sub-{want.name}", "network_id": net_id, "cidr": want.cidr,
                        "gateway_ip": want.cidr.replace("0/24", "1") if want.gateway else None})
    return networks, subnets

def planned(ports=(), servers=(), ready=READY):
    networks, subnets = fabric_standing()
    return slot.plan(DECLARED, networks, subnets, list(ports), list(servers), ready)

def test_an_empty_slot_boots_every_host_with_a_port_on_each_of_its_segments():
    plan = planned()

    assert not plan.blocked
    assert set(plan.boot) == set(DECLARED.hosts)
    assert all(fabric.MANAGEMENT in entry.segments for entry in DECLARED.hosts.values()), (
        "the platform reaches every host on management")
    assert {(p.host, p.segment) for p in plan.ports} == {
        (host, segment) for host, entry in DECLARED.hosts.items() for segment in entry.segments
    }
    assert {p.name for p in plan.ports} == {
        f"{p.host}.{p.segment}" for p in plan.ports
    }

def test_the_edge_holds_every_origins_gateway_and_the_estate_gateway():
    edge = DECLARED.roles["edge"]
    ports = planned().ports

    [internet] = [p for p in ports if p.segment == "internet" and p.host == edge]
    [estate] = [p for p in ports if p.host == edge and p.segment == "estate"]

    assert sorted(address for _, address in internet.fixed_ips) == sorted(
        o.subnet.replace("0/24", "1") for o in DECLARED.origins
    )
    assert {subnet for subnet, _ in internet.fixed_ips} == {f"sub-fsl-{o.id}" for o in DECLARED.origins}
    assert [address for _, address in estate.fixed_ips] == ["10.30.0.1"], (
        "the estate's hosts default-route to the edge, so the edge has to "
        "answer at the estate's gateway address"
    )

def test_the_attacker_holds_the_declared_per_country_addresses_on_the_internet():
    attacker = DECLARED.roles["attacker"]

    [port] = [p for p in planned().ports if p.host == attacker and p.segment == "internet"]

    held = sorted(address for _, address in port.fixed_ips)
    assert len(held) == sum(o.addresses for o in DECLARED.origins), (
        "the attacker can only wear a source address its port already owns, or "
        "Neutron anti-spoofing drops the packet"
    )
    by_subnet = {}
    for subnet, address in port.fixed_ips:
        by_subnet.setdefault(subnet, []).append(address)
    for origin in DECLARED.origins:
        wanted = slot.origin_addresses(origin.subnet, origin.addresses)
        assert set(wanted) <= set(held), origin.id
        assert sorted(by_subnet[f"sub-fsl-{origin.id}"]) == sorted(wanted), origin.id
        assert all(a not in wanted for a in (origin.subnet.replace("0/24", "1"),)), (
            "the gateway .1 is the edge's; the attacker must not claim it"
        )

def test_a_host_standing_is_not_booted_again_and_its_ports_stay():
    servers = [{"id": "srv-1", "name": "fsl-wargame-host", "status": "ACTIVE",
                "metadata": {slot.HOST: "fsl-wargame-host"}}]

    plan = planned(servers=servers)

    assert "fsl-wargame-host" not in plan.boot
    assert ("fsl-wargame-host", "srv-1", "ACTIVE") in plan.standing
    assert not [p for p in plan.ports if p.host == "fsl-wargame-host"]

def test_a_port_left_from_an_earlier_try_is_used_not_made_again():
    left = [{"id": "port-9", "name": "fsl-wargame-host.estate", "network_id": "net-estate"}]

    plan = planned(ports=left)

    assert "fsl-wargame-host.estate" not in {p.name for p in plan.ports}
    assert "fsl-wargame-host" in plan.boot

def test_a_host_that_is_neither_edge_nor_attacker_may_not_stand_on_the_internet(tmp_path):
    document = yaml.safe_load((ROOT / "platform/range/declaration.yaml").read_text())
    document["hosts"]["fsl-wargame-host"]["segments"] = ["estate", "mgmt", "internet"]
    path = tmp_path / "declaration.yaml"
    path.write_text(yaml.safe_dump(document))
    networks, subnets = fabric_standing()

    plan = slot.plan(declared.read(path), networks, subnets, [], [], READY)

    assert any("fsl-wargame-host" in reason and "internet" in reason for reason in plan.blocked)

def config(**given):
    text = base64.b64decode(slot.user_data(**given)).decode()
    assert text.startswith("#cloud-config\n")
    return yaml.safe_load(text)

def test_every_host_learns_the_others_names_on_the_estate():
    found = config(names={"10.30.0.5": ["juice-shop"], "10.30.0.7": ["wiki", "wiki.internal"]})

    [hosts] = [f for f in found["write_files"] if f["path"] == "/etc/hosts"]
    assert hosts["append"] is True
    assert hosts["content"].splitlines() == ["10.30.0.5 juice-shop", "10.30.0.7 wiki wiki.internal"]
    assert found["manage_etc_hosts"] is False, (
        "cloud-init rewriting /etc/hosts from its template would drop the names"
    )
    assert "bootcmd" not in found

def test_the_gateway_puts_every_address_of_its_internet_port_on_that_nic_each_boot():
    found = config(names={}, mac="fa:16:3e:00:00:01",
                   addresses=("73.0.0.1/24", "117.192.0.1/24"))

    [command] = found["bootcmd"]
    script = command[-1]
    assert "fa:16:3e:00:00:01" in script
    assert "ip addr replace" in script
    assert "73.0.0.1/24" in script and "117.192.0.1/24" in script

@pytest.mark.parametrize("plan, active", [
    (slot.Plan(standing=(("fsl-waf", "s1", "ACTIVE"), ("fsl-juice-shop", "s2", "ACTIVE"))), True),
    (slot.Plan(standing=(("fsl-waf", "s1", "ACTIVE"), ("fsl-juice-shop", "s2", "REBUILD"))), False),
    (slot.Plan(standing=(("fsl-waf", "s1", "BUILD"),)), False),
    (slot.Plan(boot=("fsl-wiki",), standing=(("fsl-waf", "s1", "ACTIVE"),)), False),
    (slot.Plan(standing=(("fsl-waf", "s1", "ACTIVE"),), blocked=("image fsl-wargame-host is not ready",)), False),
    (slot.Plan(), False),
], ids=["standing", "rebuilding", "booting", "to-boot", "blocked", "empty"])
def test_a_slot_is_active_only_when_every_host_stands_active_and_nothing_blocks_it(plan, active):
    assert plan.active is active
