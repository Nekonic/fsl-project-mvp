import inspect
import pathlib
import re
import shlex
import subprocess

import pytest

from range import declared, docker, openstack, ports
from range.ports import RangeUnavailable

PLATFORM = pathlib.Path(__file__).resolve().parents[1]

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


def cloud_reader(networks=None, asked=None):
    def get(call):
        if asked is not None:
            asked.append(call)
        if "/v2.0/networks" in call:
            return networks if networks is not None else NETWORKS
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        if "/servers/detail" in call:
            return SERVERS
        raise AssertionError(call)

    return get


def sketch(networks=None, asked=None):
    return openstack.OpenStack(
        declared.read(), CLOUD, get=cloud_reader(networks, asked)
    )


def test_the_sketch_offers_the_same_port_the_docker_adapter_does():
    for verb in ("describe", "runner", "launcher"):
        assert inspect.signature(
            getattr(openstack.OpenStack, verb)
        ) == inspect.signature(getattr(docker.Docker, verb))


def test_nothing_at_runtime_imports_the_openstack_adapter():
    importing = re.compile(
        r"^\s*(from range\.openstack import|import range\.openstack|"
        r"from range import .*\bopenstack\b)", re.M,
    )
    importers = [
        str(path.relative_to(PLATFORM))
        for path in PLATFORM.rglob("*.py")
        if path.parent.name != "tests"
        and path.name != "openstack.py"
        and importing.search(path.read_text())
    ]

    assert importers == [], (
        f"{importers} import the OpenStack adapter, so a Docker deployment "
        f"loads it too. It is loaded by name, only when FSL_SUBSTRATE says so"
    )


def test_the_declaration_alone_gives_every_segment_its_identity():
    shape = sketch().describe()
    edge = next(segment for segment in shape.segments if segment.id == "ru")
    estate = next(segment for segment in shape.segments if segment.id == "estate")

    assert (edge.name, edge.origin, edge.outside) == ("Internet", "Russia", True)
    assert (estate.name, estate.origin, estate.outside) == ("Application estate", "", False)


def test_the_cloud_supplies_only_what_it_allocated():
    edge = next(s for s in sketch().describe().segments if s.id == "ru")

    assert (edge.subnet, edge.gateway, edge.network) == (
        "5.188.10.0/24", "5.188.10.1", "net-internet",
    )
    assert [(node.name, node.address) for node in edge.nodes] == [
        ("fsl-kali", "5.188.10.7"), ("fsl-waf", "5.188.10.9"),
    ]


def test_a_network_the_range_does_not_tag_is_dropped_not_drawn():
    ids = [segment.id for segment in sketch().describe().segments]

    assert "tenant-scratch" not in ids, (
        "unlike compose, a Neutron project holds networks that are not the "
        "range, so the adapter can only keep what the range marked"
    )


def test_a_segment_is_bound_by_its_tag_and_not_by_what_it_is_called():
    edge = next(s for s in sketch().describe().segments if s.id == "ru")

    assert edge.network == "net-internet", (
        "the segment was found by a network whose name happened to equal the "
        "declared id. Neutron names are neither unique nor the operator's to "
        "keep, and Heat appends its own stack suffix to every one of them"
    )


def test_the_cloud_is_asked_only_for_the_networks_the_range_marked():
    asked = []
    sketch(asked=asked).describe()

    listing = next(call for call in asked if "/v2.0/networks" in call)

    assert "tags-any=" in listing, (
        "every network in the project came back and the adapter sorted them "
        "out afterwards; a shared project hands back other people's networks"
    )
    assert tagged("internet") in listing


def allocated_on(network_id, subnets):
    reader = cloud_reader()

    def get(call):
        if "/v2.0/subnets" in call and call.endswith(f"={network_id}"):
            return {"subnets": subnets}
        return reader(call)

    return openstack.OpenStack(declared.read(), CLOUD, get=get)


def test_a_dual_stack_segment_is_bound_to_its_ipv4_subnet():
    estate = next(s for s in allocated_on("net-estate", [
        {"cidr": "fd00:172:30::/64", "gateway_ip": "fd00:172:30::1",
         "ip_version": 6},
        {"cidr": "172.30.0.0/24", "gateway_ip": "172.30.0.1", "ip_version": 4},
    ]).describe().segments if s.id == "estate")

    assert (estate.subnet, estate.gateway) == ("172.30.0.0/24", "172.30.0.1"), (
        "the segment took whichever subnet Neutron listed first, so a "
        "dual-stack network became an IPv6 zone and every IPv4 alert from it "
        "sat on no segment at all"
    )


def test_a_segment_with_two_ipv4_subnets_is_refused_and_named():
    with pytest.raises(RangeUnavailable) as raised:
        allocated_on("net-estate", [
            {"cidr": "172.30.0.0/24", "gateway_ip": "172.30.0.1", "ip_version": 4},
            {"cidr": "172.30.1.0/24", "gateway_ip": "172.30.1.1", "ip_version": 4},
        ]).describe()

    assert "'estate'" in str(raised.value), raised.value
    assert "172.30.1.0/24" in str(raised.value), (
        "alerts are binned by exactly one subnet, and which of two it is was "
        "decided by the order Neutron listed them in"
    )


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


def test_a_subnet_no_origin_declares_is_refused_and_named():
    stray = SUBNETS["net-internet"]["subnets"] + [
        {"cidr": "175.45.176.0/24", "gateway_ip": "175.45.176.1"}
    ]

    with pytest.raises(RangeUnavailable, match="175.45.176.0/24"):
        allocated_on("net-internet", stray).describe()


def test_an_origin_the_cloud_gave_no_subnet_is_named():
    short = [s for s in SUBNETS["net-internet"]["subnets"] if s["cidr"] != "103.152.220.0/24"]

    with pytest.raises(RangeUnavailable, match="origin 'hk' is declared on 103.152.220.0/24"):
        allocated_on("net-internet", short).describe()


def test_a_segment_the_cloud_does_not_have_is_named_rather_than_skipped():
    short = {
        "networks": [n for n in NETWORKS["networks"] if n["id"] != "net-estate"]
    }

    with pytest.raises(RangeUnavailable) as raised:
        sketch(short).describe()

    assert "the declaration names the segment 'estate'" in str(raised.value)


def test_what_the_sensor_watches_comes_from_the_roles_and_not_the_cloud():
    shape = sketch().describe()

    assert [(s.name, s.watches) for s in shape.sensors] == [
        ("fsl-suricata", "fsl-waf")
    ], (
        "Neutron has no namespace sharing to read this off, and the sketch "
        "used to assume the sensor watches the gateway. It is declared now, "
        "and nothing on Nova confirms it"
    )


def test_a_role_no_server_fills_is_refused():
    with pytest.raises(RangeUnavailable) as raised:
        sketch().runner("board")(["true"])

    assert "board" in str(raised.value) and "fsl-wg-board" in str(raised.value)


def test_the_cloud_field_constants_match_the_api_reference():
    assert openstack.FIXED == "OS-EXT-IPS:type"
    assert openstack.LAUNCHED == "OS-SRV-USG:launched_at"
    assert "tags-any" in openstack.NETWORKS


def test_an_ipv6_address_is_not_taken_for_the_address_of_a_node():
    dual = {
        "servers": [{
            "name": "fsl-waf",
            "addresses": {"range1-internet-v4": [
                {"addr": "fd00:5:188:10::9", "OS-EXT-IPS:type": "fixed", "version": 6},
                {"addr": "5.188.10.9", "OS-EXT-IPS:type": "fixed", "version": 4},
            ]},
        }]
    }

    def reader(call):
        if "/v2.0/networks" in call:
            return NETWORKS
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        return dual

    shape = openstack.OpenStack(declared.read(), CLOUD, get=reader).describe()
    edge = next(s for s in shape.segments if s.id == "ru")

    assert [n.address for n in edge.nodes] == ["5.188.10.9"], (
        "Nova reports every fixed address a port has, and an instance with a "
        "v6 address would have been drawn at it - while the console bins every "
        "alert by an IPv4 subnet, so it would sit on no segment at all"
    )


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

def test_nothing_on_nova_tells_the_scoreboard_the_operator_is_outside():
    shape = sketch().describe()

    gateways = {segment.gateway for segment in shape.segments if segment.gateway}
    nodes = {n.address for s in shape.segments for n in s.nodes}

    assert not (gateways & nodes), (
        "a gateway that is also a node would let the red team in"
    )
    assert gateways, (
        "On Docker the operator's console arrives from a segment's gateway "
        "because the published port is DNATed, which is what distinguishes it "
        "from a host inside the range. A Neutron router does the same for a "
        "floating IP, but the sketch cannot confirm it without a cloud - this "
        "test only records that Shape carries the gateway the rule needs"
    )


def paged(pages):
    calls = []

    def get(call):
        calls.append(call)
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        if "/servers/detail" in call:
            return SERVERS
        return pages.pop(0) if pages else {"networks": []}

    get.calls = calls
    return get

def test_a_list_that_arrives_in_pages_is_read_to_the_end():
    everything = NETWORKS["networks"]
    first = {
        "networks": everything[:2],
        "networks_links": [
            {"href": "http://neutron:9696/v2.0/networks?marker=net-br",
             "rel": "next"},
            {"href": "http://neutron:9696/v2.0/networks", "rel": "previous"},
        ],
    }
    rest = {"networks": everything[2:]}

    shape = openstack.OpenStack(
        declared.read(), CLOUD, get=paged([first, rest])
    ).describe()

    assert {s.id for s in shape.segments} == set(ALLOCATED), (
        "Neutron's own example response for List Networks is labelled 'first "
        "page' and carries networks_links rel=next. Reading only the first "
        "page drops whatever segments fall past the page limit, and describe() "
        "then reports them as segments the cloud does not have"
    )

def test_following_a_page_asks_for_exactly_the_href_the_cloud_gave():
    everything = NETWORKS["networks"]
    href = "http://neutron:9696/v2.0/networks?limit=2&marker=net-br"
    get = paged([
        {"networks": everything[:2],
         "networks_links": [{"href": href, "rel": "next"}]},
        {"networks": everything[2:]},
    ])

    openstack.OpenStack(declared.read(), CLOUD, get=get).describe()

    followed = [c for c in get.calls if "marker=" in c]
    assert followed == [f"GET {href}"], (
        f"the next page was fetched by rebuilding a URL rather than by using "
        f"the href the cloud handed back, so any filter or limit in it is "
        f"lost: {followed}"
    )

def test_a_page_link_that_loops_does_not_hang_the_console():
    href = "http://neutron:9696/v2.0/networks?marker=stuck"
    forever = {
        "networks": NETWORKS["networks"][:1],
        "networks_links": [{"href": href, "rel": "next"}],
    }

    def get(call):
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        if "/servers/detail" in call:
            return SERVERS
        return forever

    with pytest.raises(RangeUnavailable, match="pages"):
        openstack.OpenStack(declared.read(), CLOUD, get=get).describe()


def test_a_paginated_server_list_is_read_to_the_end():
    everything = SERVERS["servers"]

    def get(call):
        if "/v2.0/networks" in call:
            return NETWORKS
        if "/v2.0/subnets" in call:
            return SUBNETS[call.rsplit("=", 1)[1]]
        if "marker=" in call:
            return {"servers": everything[1:]}
        return {
            "servers": everything[:1],
            "servers_links": [
                {"href": "http://nova:8774/servers/detail?marker=one",
                 "rel": "next"}
            ],
        }

    shape = openstack.OpenStack(declared.read(), CLOUD, get=get).describe()
    named = {n.name for s in shape.segments for n in s.nodes}

    assert "fsl-waf" in named, (
        "Nova documents servers_links as present 'when the number of servers "
        "exceeds limit parameter or [api]/max_limit', so on any range bigger "
        "than one page the hosts past the first page vanish from the map and "
        "from every alert's host name"
    )

def test_a_list_as_long_as_the_page_limit_is_read_to_the_end():
    assert openstack.PAGE_LIMIT >= 10, openstack.PAGE_LIMIT

    everything = NETWORKS["networks"]
    following = [{"href": "http://neutron:9696/v2.0/networks?marker=next", "rel": "next"}]
    pages = (
        [{"networks": everything[:3], "networks_links": following}]
        + [{"networks": [], "networks_links": following}] * (openstack.PAGE_LIMIT - 2)
        + [{"networks": everything[3:]}]
    )

    shape = openstack.OpenStack(declared.read(), CLOUD, get=paged(pages)).describe()

    assert {s.id for s in shape.segments} == set(ALLOCATED)


def test_a_tool_runs_on_the_attacker_that_stands_on_that_segment():
    from unittest.mock import patch

    from range.ports import Ran

    adapter = sketch()
    with patch("range.openstack.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = "sqlmap 1.10"
        ran.return_value.stderr = f"{ports.EXIT_MARK}0\n"
        answered = adapter.launcher("ru")("fsl-kali", ["sqlmap", "--version"])

    argv = ran.call_args.args[0]
    assert argv[0] == "ssh", argv
    assert shlex.split(argv[-1]) == [
        "sh", "-c", f'"$@"; {ports.EXIT_REPORT}', "sh", "sqlmap", "--version",
    ], argv
    assert "5.188.10.7@".split("@")[0] in " ".join(argv), (
        f"the tool did not run on the attacker's address on the edge segment: "
        f"{argv}"
    )
    assert answered.output == "sqlmap 1.10"

def test_a_tool_on_a_segment_the_attacker_does_not_stand_on_is_refused():
    adapter = sketch()

    with pytest.raises(RangeUnavailable) as raised:
        adapter.launcher("us")("fsl-kali", ["sqlmap"])

    assert "us" in str(raised.value) and "fsl-kali" in str(raised.value), (
        "Nova has no docker run --rm: there is no way to boot a host, capture "
        "its stdout and delete it in one call. A tool runs on an attacker that "
        "already stands on that segment, so the range must provide one per "
        "origin - and the declaration has a single attacker role"
    )

def test_the_image_is_not_silently_ignored():
    adapter = sketch()

    with pytest.raises(RangeUnavailable, match="image"):
        adapter.launcher("ru")("some-other-image", ["sqlmap"])

def test_reaching_a_host_does_not_read_the_whole_cloud_every_command():
    from unittest.mock import patch

    asked = []
    adapter = openstack.OpenStack(
        declared.read(), CLOUD, get=cloud_reader(asked=asked)
    )
    run = adapter.runner("gateway")
    with patch("range.openstack.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = ""
        ran.return_value.stderr = f"{ports.EXIT_MARK}0\n"
        for _ in range(4):
            run(["true"])

    listings = [c for c in asked if "/v2.0/networks" in c]
    assert len(listings) == 1, (
        f"every command re-read the whole cloud: {len(listings)} network listings "
        f"for four commands. Applying one Suricata rule set is a validate, a "
        f"read, a write and a reload"
    )


def test_the_shape_is_read_once_per_adapter_and_not_once_per_platform():
    asked = []
    adapter = openstack.OpenStack(declared.read(), CLOUD, get=cloud_reader(asked=asked))

    adapter.describe()
    adapter.describe()

    listings = [c for c in asked if "/v2.0/networks" in c]
    assert len(listings) == 1, listings

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

def reached_at(monkeypatch, segment_id=""):
    base = cloud_reader()

    def get(call):
        return ON_THREE if "/servers/detail" in call else base(call)

    reached = []

    def execute(host, command, stdin, timeout):
        reached.append(command[-2])
        return subprocess.CompletedProcess(command, 0, "", f"{ports.EXIT_MARK}0\n")

    monkeypatch.setattr(openstack, "execute", execute)
    openstack.OpenStack(declared.read(), CLOUD, get=get).runner("gateway", segment_id)(["true"])
    return reached

def test_a_host_is_reached_on_management_when_no_segment_is_named(monkeypatch):
    assert reached_at(monkeypatch) == ["fsl@172.31.0.9"], (
        "the platform stands only on management; the WAF's first address is "
        "an origin gateway it has no route to"
    )

def test_a_named_segment_still_picks_the_address_there(monkeypatch):
    assert reached_at(monkeypatch, "estate") == ["fsl@172.30.0.9"]
