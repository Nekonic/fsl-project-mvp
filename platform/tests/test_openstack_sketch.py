import inspect
import subprocess

import pytest

from range import declared, docker, openstack, ports
from range.ports import RangeUnavailable

CLOUD = openstack.Cloud(
    keystone="http://keystone:5000",
    neutron="http://neutron:9696",
    nova="http://nova:8774",
    project="fsl",
    user="fsl",
    ssh_user="fsl",
    ssh_key="/keys/fsl",
)

ALLOCATED = {
    **{origin.id: origin.subnet for origin in declared.read().origins},
    "estate": "172.30.0.0/24",
    "mgmt": "172.31.0.0/24",
}

def tagged(segment_id):
    return f"{openstack.SEGMENT_TAG}={segment_id}"

CARRIER = {origin.id: origin.segment for origin in declared.read().origins}

def carrier(segment_id):
    return CARRIER.get(segment_id, segment_id)

NETWORKS = {
    "networks": [
        {"id": f"net-{name}", "name": f"range1-{name}-v4", "tags": [tagged(name)]}
        for name in dict.fromkeys(carrier(segment) for segment in ALLOCATED)
    ]
    + [{"id": "net-unrelated", "name": "tenant-scratch", "tags": []}]
}

SUBNETS = {
    f"net-{name}": {
        "subnets": [
            {"cidr": cidr, "gateway_ip": cidr.replace("0/24", "1")}
            for segment, cidr in ALLOCATED.items() if carrier(segment) == name
        ]
    }
    for name in dict.fromkeys(carrier(segment) for segment in ALLOCATED)
}

SERVERS = {
    "servers": [
        {
            "name": "fsl-kali",
            "addresses": {
                "range1-internet-v4": [{"addr": "5.188.10.7", "OS-EXT-IPS:type": "fixed"}]
            },
        },
        {
            "name": "fsl-waf",
            "addresses": {
                "range1-internet-v4": [
                    {"addr": "5.188.10.9", "OS-EXT-IPS:type": "fixed"},
                    {"addr": "192.0.2.9", "OS-EXT-IPS:type": "floating"},
                ],
                "range1-estate-v4": [
                    {"addr": "172.30.0.9", "OS-EXT-IPS:type": "fixed"}
                ],
            },
        },
        {
            "name": "fsl-suricata",
            "addresses": {
                "range1-estate-v4": [
                    {"addr": "172.30.0.11", "OS-EXT-IPS:type": "fixed"}
                ]
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
    for verb in ("describe", "runner", "launcher"):
        assert inspect.signature(
            getattr(openstack.OpenStack, verb)
        ) == inspect.signature(getattr(docker.Docker, verb))


def test_the_cloud_supplies_only_what_it_allocated():
    edge = next(s for s in sketch().describe().segments if s.id == "ru")

    assert (edge.subnet, edge.gateway, edge.network) == (
        "5.188.10.0/24", "5.188.10.1", "net-internet",
    )
    assert [(node.name, node.address) for node in edge.nodes] == [
        ("fsl-kali", "5.188.10.7"), ("fsl-waf", "5.188.10.9"),
    ]


def allocated_on(network_id, subnets):
    reader = cloud_reader()

    def get(call):
        if "/v2.0/subnets" in call and call.endswith(f"={network_id}"):
            return {"subnets": subnets}
        return reader(call)

    return openstack.OpenStack(declared.read(), CLOUD, get=get)


def test_two_networks_claiming_the_same_segment_are_refused_not_guessed():
    doubled = {"networks": NETWORKS["networks"] + [
        {"id": "net-internet-2", "name": "range1-internet-legacy", "tags": [tagged("internet")]}
    ]}

    with pytest.raises(RangeUnavailable) as raised:
        sketch(doubled).describe()

    assert "both carry" in str(raised.value) and "'internet'" in str(raised.value)


def test_every_origin_is_one_subnet_of_the_internet_network_and_keeps_its_own_hosts():
    shape = sketch().describe()
    by_id = {segment.id: segment for segment in shape.segments}
    origins = declared.read().origins

    assert [(by_id[o.id].subnet, by_id[o.id].network) for o in origins] == [
        (o.subnet, "net-internet") for o in origins
    ]
    assert [n.name for n in by_id["ru"].nodes] == ["fsl-kali", "fsl-waf"]
    assert not by_id["us"].nodes, (
        "every host on the shared Internet network was put on every origin, "
        "so an alert from Moscow could be binned to Seattle"
    )


def without_network(network_id):
    return sketch({"networks": [n for n in NETWORKS["networks"] if n["id"] != network_id]})


@pytest.mark.parametrize("adapter, named", [
    (lambda: allocated_on("net-internet", SUBNETS["net-internet"]["subnets"] + [
        {"cidr": "175.45.176.0/24", "gateway_ip": "175.45.176.1"}]), "175.45.176.0/24"),
    (lambda: allocated_on("net-internet", [
        s for s in SUBNETS["net-internet"]["subnets"] if s["cidr"] != "103.152.220.0/24"]),
     "origin 'hk' is declared on 103.152.220.0/24"),
    (lambda: without_network("net-estate"), "the declaration names the segment 'estate'"),
], ids=["subnet-no-origin-declares", "origin-without-a-subnet", "segment-the-cloud-lacks"])
def test_a_cloud_that_drifted_from_the_declaration_is_refused_and_named(adapter, named):
    with pytest.raises(RangeUnavailable, match=named):
        adapter().describe()


def test_who_may_call_the_scoreboard_is_decided_on_the_port_not_on_docker():
    from unittest.mock import patch

    from api import reachability

    shape = sketch().describe()

    with patch("api.reachability.substrate", lambda: sketch()):
        reachability._cached = (0.0, frozenset())
        standing = reachability.scored_hosts()
        reachability._cached = (0.0, frozenset())

    addresses = {
        node.address for segment in shape.segments for node in segment.nodes
    }
    scorer = declared.read().roles.get("scorer") or ""
    mine = {
        node.address for segment in shape.segments
        for node in segment.nodes if node.name == scorer
    }

    assert standing == addresses - mine, (
        "the rule that stops the red team calling the scoring API reads "
        "addresses off Shape, so it should hold on any substrate that fills "
        "Shape. If it does not, it grew a Docker assumption"
    )
    assert standing, "the sketch supplied no nodes, so this proved nothing"

def test_a_tool_reaches_the_attacker_over_management():
    from unittest.mock import patch

    servers = {"servers": [{
        "name": "fsl-kali",
        "addresses": {
            "range1-mgmt-v4": [{"addr": "172.31.0.7", "OS-EXT-IPS:type": "fixed"}],
            "range1-internet-v4": [{"addr": "5.188.10.7", "OS-EXT-IPS:type": "fixed"}],
        },
    }]}

    def get(call):
        return servers if "/servers/detail" in call else cloud_reader()(call)

    adapter = openstack.OpenStack(declared.read(), CLOUD, get=get)
    with patch("range.openstack.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = "sqlmap 1.10"
        ran.return_value.stderr = f"{ports.EXIT_MARK}0\n"
        adapter.launcher("ru")("fsl-kali", ["sqlmap", "--version"])

    target = ran.call_args.args[0][-2]
    assert target.endswith("@172.31.0.7"), (
        f"the tool ssh'd to the attacker's internet (origin) address, which the "
        f"platform has no route to; the management address is the only one it "
        f"reaches, and the origin is carried by the SNAT the proxy wears there, "
        f"not by which address ssh connects to: {target}"
    )
    assert "5.188.10.7" not in target, target

def test_a_new_adapter_sees_a_range_that_changed():
    first = openstack.OpenStack(declared.read(), CLOUD, get=cloud_reader())
    assert first.describe().segments

    moved = {"networks": [
        dict(n, id=n["id"] + "-new") for n in NETWORKS["networks"]
    ]}
    second = openstack.OpenStack(
        declared.read(), CLOUD,
        get=lambda call: (
            moved if "/v2.0/networks" in call
            else SUBNETS[call.rsplit("=", 1)[1].replace("-new", "")]
            if "/v2.0/subnets" in call else SERVERS
        ),
    )

    assert {s.network for s in second.describe().segments} != {
        s.network for s in first.describe().segments
    }, (
        "the shape is memoised on the adapter, so a platform that kept one "
        "adapter alive would keep answering with a range that no longer "
        "exists. It must be built per request, as range.substrate() does"
    )


ON_THREE = {"servers": [{
    "id": "srv-waf", "name": "fsl-waf",
    "addresses": {
        "range1-internet-v4": [{"addr": "5.188.10.9", "OS-EXT-IPS:type": "fixed"}],
        "range1-estate-v4": [{"addr": "172.30.0.9", "OS-EXT-IPS:type": "fixed"}],
        "range1-mgmt-v4": [{"addr": "172.31.0.9", "OS-EXT-IPS:type": "fixed"}],
    },
}]}

def reached_at(monkeypatch):
    base = cloud_reader()

    def get(call):
        return ON_THREE if "/servers/detail" in call else base(call)

    reached = []

    def execute(host, command, stdin, timeout):
        reached.append(command[-2])
        return subprocess.CompletedProcess(command, 0, "", f"{ports.EXIT_MARK}0\n")

    monkeypatch.setattr(openstack, "execute", execute)
    openstack.OpenStack(declared.read(), CLOUD, get=get).runner("gateway")(["true"])
    return reached

def test_a_host_is_reached_on_management_when_no_segment_is_named(monkeypatch):
    assert reached_at(monkeypatch) == ["fsl@172.31.0.9"], (
        "the platform stands only on management; the WAF's first address is "
        "an origin gateway it has no route to"
    )

def test_the_board_is_addressed_on_management_not_on_the_estate():
    servers = {"servers": [{
        "name": "fsl-wg-board",
        "addresses": {
            "range1-estate-v4": [{"addr": "10.20.0.9", "OS-EXT-IPS:type": "fixed"}],
            "range1-mgmt-v4": [{"addr": "172.31.0.9", "OS-EXT-IPS:type": "fixed"}],
        },
    }]}

    def get(call):
        return servers if "/servers/detail" in call else cloud_reader()(call)

    found = openstack.OpenStack(declared.read(), CLOUD, get=get).address("board")

    assert found == "172.31.0.9", (
        "the platform reaches range hosts over management only, and the board "
        f"VM's address there is handed out by DHCP, so it is read from the cloud: {found}"
    )
