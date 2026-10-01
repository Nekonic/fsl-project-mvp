import base64
import pathlib

import pytest
import yaml

from range import declared, fabric, slot

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
READY = {host: f"img-{host}" for host in DECLARED.hosts}

def fabric_standing():
    networks, subnets = [], []
    for want in fabric.wanted(DECLARED):
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

    assert set(plan.boot) == set(DECLARED.hosts)
    assert {(p.host, p.segment) for p in plan.ports} == {
        (host, segment) for host, entry in DECLARED.hosts.items() for segment in entry.segments
    }
    assert {p.name for p in plan.ports} == {
        f"{p.host}.{p.segment}" for p in plan.ports
    }

def test_the_gateway_holds_every_origins_gateway_on_the_internet():
    gateway = DECLARED.roles["gateway"]

    [port] = [p for p in planned().ports if p.segment == "internet"]

    assert port.host == gateway
    assert sorted(address for _, address in port.fixed_ips) == sorted(
        o.subnet.replace("0/24", "1") for o in DECLARED.origins
    )
    assert {subnet for subnet, _ in port.fixed_ips} == {f"sub-fsl-{o.id}" for o in DECLARED.origins}

def test_a_port_on_a_network_with_dhcp_takes_the_address_neutron_gives():
    assert all(not p.fixed_ips for p in planned().ports if p.segment != "internet")

def test_a_host_standing_is_not_booted_again_and_its_ports_stay():
    servers = [{"id": "srv-1", "name": "fsl-wiki", "status": "ACTIVE",
                "metadata": {slot.HOST: "fsl-wiki"}}]

    plan = planned(servers=servers)

    assert "fsl-wiki" not in plan.boot
    assert ("fsl-wiki", "srv-1", "ACTIVE") in plan.standing
    assert not [p for p in plan.ports if p.host == "fsl-wiki"]

def test_a_port_left_from_an_earlier_try_is_used_not_made_again():
    left = [{"id": "port-9", "name": "fsl-wiki.estate", "network_id": "net-estate"}]

    plan = planned(ports=left)

    assert "fsl-wiki.estate" not in {p.name for p in plan.ports}
    assert "fsl-wiki" in plan.boot

def test_a_host_whose_image_is_not_ready_blocks_the_slot_by_name():
    plan = planned(ready={h: i for h, i in READY.items() if h != "fsl-board"})

    assert any("fsl-board" in reason for reason in plan.blocked)

def test_a_fabric_without_a_segment_blocks_the_slot_by_name():
    networks, subnets = fabric_standing()
    networks = [n for n in networks if n["id"] != "net-estate"]

    plan = slot.plan(DECLARED, networks, subnets, [], [], READY)

    assert any("estate" in reason for reason in plan.blocked)

def test_only_the_gateway_may_stand_on_the_internet_for_now(tmp_path):
    document = yaml.safe_load((ROOT / "platform/range/declaration.yaml").read_text())
    document["hosts"]["fsl-wiki"]["segments"].append("internet")
    path = tmp_path / "declaration.yaml"
    path.write_text(yaml.safe_dump(document))
    networks, subnets = fabric_standing()

    plan = slot.plan(declared.read(path), networks, subnets, [], [], READY)

    assert any("fsl-wiki" in reason and "internet" in reason for reason in plan.blocked)

def test_every_host_stands_on_management_where_the_platform_reaches_it():
    for host, entry in DECLARED.hosts.items():
        assert fabric.MANAGEMENT in entry.segments, host

def test_a_hosts_segments_are_ones_the_fabric_builds():
    built = {want.segment for want in fabric.wanted(DECLARED)}

    for host, entry in DECLARED.hosts.items():
        assert set(entry.segments) <= built, host

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
