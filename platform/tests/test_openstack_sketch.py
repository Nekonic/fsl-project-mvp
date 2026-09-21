import inspect
import pathlib

import pytest

from range import declared, docker, openstack
from range.ports import RangeUnavailable

PLATFORM = pathlib.Path(__file__).resolve().parents[1]

CLOUD = openstack.Cloud(
    keystone="http://keystone:5000",
    neutron="http://neutron:9696",
    nova="http://nova:8774",
    project="fsl",
    ssh_user="fsl",
    ssh_key="/keys/fsl",
)

ALLOCATED = {
    "edge": "5.188.10.0/24",
    "edge-br": "177.54.144.0/24",
    "edge-hk": "103.152.220.0/24",
    "edge-kp": "175.45.176.0/24",
    "estate": "172.30.0.0/24",
    "mgmt": "172.31.0.0/24",
}

NETWORKS = {
    "networks": [{"id": f"net-{name}", "name": name} for name in ALLOCATED]
    + [{"id": "net-unrelated", "name": "tenant-scratch"}]
}

SUBNETS = {
    f"net-{name}": {
        "subnets": [{"cidr": cidr, "gateway_ip": cidr.replace("0/24", "1")}]
    }
    for name, cidr in ALLOCATED.items()
}

SERVERS = {
    "servers": [
        {
            "name": "fsl-kali",
            "addresses": {
                "edge": [{"addr": "5.188.10.7", "OS-EXT-IPS:type": "fixed"}]
            },
        },
        {
            "name": "fsl-waf",
            "addresses": {
                "edge": [
                    {"addr": "5.188.10.9", "OS-EXT-IPS:type": "fixed"},
                    {"addr": "192.0.2.9", "OS-EXT-IPS:type": "floating"},
                ],
                "estate": [{"addr": "172.30.0.9", "OS-EXT-IPS:type": "fixed"}],
            },
        },
        {
            "name": "fsl-suricata",
            "addresses": {
                "estate": [{"addr": "172.30.0.11", "OS-EXT-IPS:type": "fixed"}]
            },
        },
    ]
}


def cloud_reader(networks=None):
    def get(call):
        if "/v2.0/networks" in call:
            return networks if networks is not None else NETWORKS
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        if "/servers/detail" in call:
            return SERVERS
        raise AssertionError(call)

    return get


def sketch(networks=None):
    return openstack.OpenStack(declared.read(), CLOUD, get=cloud_reader(networks))


def test_the_sketch_offers_the_same_port_the_docker_adapter_does():
    for verb in ("describe", "runner"):
        assert inspect.signature(
            getattr(openstack.OpenStack, verb)
        ) == inspect.signature(getattr(docker.Docker, verb))


def test_nothing_at_runtime_imports_the_sketch():
    importers = [
        str(path.relative_to(PLATFORM))
        for path in PLATFORM.rglob("*.py")
        if path.parent.name != "tests"
        and path.name != "openstack.py"
        and "openstack" in path.read_text()
    ]

    assert importers == [], (
        f"the sketch exists to be read, not run, and {importers} would carry "
        f"an unfinished adapter into a release"
    )


def test_the_declaration_alone_gives_every_segment_its_identity():
    shape = sketch().describe()
    edge = next(segment for segment in shape.segments if segment.id == "edge")
    estate = next(segment for segment in shape.segments if segment.id == "estate")

    assert (edge.name, edge.origin, edge.outside) == ("Internet", "Moscow, Russia", True)
    assert (estate.name, estate.origin, estate.outside) == ("Application estate", "", False)


def test_the_cloud_supplies_only_what_it_allocated():
    edge = next(s for s in sketch().describe().segments if s.id == "edge")

    assert (edge.subnet, edge.gateway, edge.network) == (
        "5.188.10.0/24", "5.188.10.1", "net-edge",
    )
    assert [(node.name, node.address) for node in edge.nodes] == [
        ("fsl-kali", "5.188.10.7"), ("fsl-waf", "5.188.10.9"),
    ]


def test_a_network_the_declaration_never_named_is_dropped_not_drawn():
    ids = [segment.id for segment in sketch().describe().segments]

    assert "tenant-scratch" not in ids, (
        "unlike compose, a Neutron project holds networks that are not the "
        "range, so the adapter can only keep what the declaration named"
    )


def test_two_networks_of_the_same_name_are_refused_rather_than_guessed():
    doubled = {"networks": NETWORKS["networks"] + [{"id": "net-edge-2", "name": "edge"}]}

    with pytest.raises(RangeUnavailable) as raised:
        sketch(doubled).describe()

    assert "two Neutron networks are named 'edge'" in str(raised.value)


def test_a_segment_the_cloud_does_not_have_is_named_rather_than_skipped():
    short = {
        "networks": [n for n in NETWORKS["networks"] if n["name"] != "estate"]
    }

    with pytest.raises(RangeUnavailable) as raised:
        sketch(short).describe()

    assert "the declaration names the segment 'estate'" in str(raised.value)


def test_what_the_sensor_watches_comes_from_the_roles_and_not_the_cloud():
    shape = sketch().describe()

    assert [(s.name, s.watches) for s in shape.sensors] == [
        ("fsl-suricata", "fsl-waf")
    ], (
        "Neutron has no namespace sharing to read this off, so the sketch "
        "assumes the sensor watches the gateway; nothing in the declaration "
        "says so"
    )


def test_a_role_no_server_fills_is_refused():
    with pytest.raises(RangeUnavailable) as raised:
        sketch().runner("wiki")(["true"])

    assert "wiki" in str(raised.value) and "fsl-wiki" in str(raised.value)


def test_the_only_unimplemented_part_is_the_cloud_call_itself():
    bare = openstack.OpenStack(declared.read(), CLOUD)

    with pytest.raises(NotImplementedError) as raised:
        bare.describe()

    assert "/v2.0/networks" in str(raised.value)
    assert all(call in str(raised.value) for call in openstack.CALLS)
