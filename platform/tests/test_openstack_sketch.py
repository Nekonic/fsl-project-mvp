import inspect
import pathlib
import shlex

import pytest

from range import declared, docker, openstack
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
    "edge": "5.188.10.0/24",
    "edge-br": "177.54.144.0/24",
    "edge-hk": "103.152.220.0/24",
    "edge-kp": "175.45.176.0/24",
    "estate": "172.30.0.0/24",
    "mgmt": "172.31.0.0/24",
}

def tagged(segment_id):
    return f"{openstack.SEGMENT_TAG}={segment_id}"

NETWORKS = {
    "networks": [
        {"id": f"net-{name}", "name": f"range1-{name}-v4", "tags": [tagged(name)]}
        for name in ALLOCATED
    ]
    + [{"id": "net-unrelated", "name": "tenant-scratch", "tags": []}]
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
                "range1-edge-v4": [{"addr": "5.188.10.7", "OS-EXT-IPS:type": "fixed"}]
            },
        },
        {
            "name": "fsl-waf",
            "addresses": {
                "range1-edge-v4": [
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


def test_a_network_the_range_does_not_tag_is_dropped_not_drawn():
    ids = [segment.id for segment in sketch().describe().segments]

    assert "tenant-scratch" not in ids, (
        "unlike compose, a Neutron project holds networks that are not the "
        "range, so the adapter can only keep what the range marked"
    )


def test_a_segment_is_bound_by_its_tag_and_not_by_what_it_is_called():
    edge = next(s for s in sketch().describe().segments if s.id == "edge")

    assert edge.network == "net-edge", (
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
    assert tagged("edge") in listing


def test_two_networks_claiming_the_same_segment_are_refused_not_guessed():
    doubled = {"networks": NETWORKS["networks"] + [
        {"id": "net-edge-2", "name": "range1-edge-legacy", "tags": [tagged("edge")]}
    ]}

    with pytest.raises(RangeUnavailable) as raised:
        sketch(doubled).describe()

    assert "both carry" in str(raised.value) and "'edge'" in str(raised.value)


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
        sketch().runner("wiki")(["true"])

    assert "wiki" in str(raised.value) and "fsl-wiki" in str(raised.value)


def test_the_only_unimplemented_part_is_the_cloud_call_itself():
    bare = openstack.OpenStack(declared.read(), CLOUD)

    with pytest.raises(NotImplementedError) as raised:
        bare.describe()

    assert "/v2.0/networks" in str(raised.value)
    assert all(call in str(raised.value) for call in openstack.CALLS)


def test_starting_a_tool_is_a_cloud_call_the_sketch_does_not_make():
    with pytest.raises(NotImplementedError) as raised:
        openstack.OpenStack(declared.read(), CLOUD).launcher("edge")(
            "fsl-kali", ["sqlmap"]
        )

    assert openstack.BOOT in str(raised.value), (
        "docker run --rm is seconds and cleans up after itself. Nova has no "
        "such verb: a tool is a server booted from a Glance image with a "
        "flavour and a key pair, and something has to delete it afterwards"
    )


REFERENCE = {
    "networks[].id, .name, .tags": "https://docs.openstack.org/api-ref/network/v2/#list-networks",
    "?tags-any=": "https://docs.openstack.org/api-ref/network/v2/#list-networks",
    "subnets[].cidr, .gateway_ip": "https://docs.openstack.org/api-ref/network/v2/#list-subnets",
    "servers[].addresses[label][].addr, .OS-EXT-IPS:type, .version":
        "https://docs.openstack.org/api-ref/compute/#list-servers-detailed",
}

def test_every_field_the_sketch_reads_is_one_the_api_reference_names():
    source = pathlib.Path(openstack.__file__).read_text()

    for field in ("\"id\"", "\"name\"", "\"tags\"", "\"cidr\"", "\"gateway_ip\"",
                  "\"addr\"", "\"servers\"", "\"networks\"", "\"subnets\""):
        assert field in source, (
            f"{field} is how the sketch reads the cloud and nothing in it "
            f"matches the published response any more. Checked against "
            f"{REFERENCE}"
        )
    assert openstack.FIXED == "OS-EXT-IPS:type"
    assert "tags-any" in openstack.NETWORKS


def test_an_ipv6_address_is_not_taken_for_the_address_of_a_node():
    dual = {
        "servers": [{
            "name": "fsl-waf",
            "addresses": {"range1-edge-v4": [
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
    edge = next(s for s in shape.segments if s.id == "edge")

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
        reachability.forget()
        standing = reachability.scored_hosts()
        reachability.forget()

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
            {"href": "http://neutron:9696/v2.0/networks?marker=net-edge-br",
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
    href = "http://neutron:9696/v2.0/networks?limit=2&marker=net-edge-br"
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

def test_the_page_limit_is_stated_rather_than_hidden():
    assert openstack.PAGE_LIMIT >= 10, openstack.PAGE_LIMIT


def test_a_tool_runs_on_the_attacker_that_stands_on_that_segment():
    from unittest.mock import patch

    from range.ports import Ran

    adapter = sketch()
    with patch("range.openstack.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = "sqlmap 1.10"
        ran.return_value.stderr = f"{openstack.EXIT_MARK}0\n"
        answered = adapter.launcher("edge")("fsl-kali", ["sqlmap", "--version"])

    argv = ran.call_args.args[0]
    assert argv[0] == "ssh", argv
    assert shlex.split(argv[-1])[:4] == [
        "sh", "-c", "--", f"sqlmap --version; {openstack.EXIT_REPORT}",
    ], argv
    assert "5.188.10.7@".split("@")[0] in " ".join(argv), (
        f"the tool did not run on the attacker's address on the edge segment: "
        f"{argv}"
    )
    assert answered.output == "sqlmap 1.10"

def test_a_tool_on_a_segment_the_attacker_does_not_stand_on_is_refused():
    adapter = sketch()

    with pytest.raises(RangeUnavailable) as raised:
        adapter.launcher("edge-kp")("fsl-kali", ["sqlmap"])

    assert "edge-kp" in str(raised.value) and "fsl-kali" in str(raised.value), (
        "Nova has no docker run --rm: there is no way to boot a host, capture "
        "its stdout and delete it in one call. A tool runs on an attacker that "
        "already stands on that segment, so the range must provide one per "
        "origin - and the declaration has a single attacker role"
    )

def test_the_image_is_not_silently_ignored():
    adapter = sketch()

    with pytest.raises(RangeUnavailable, match="image"):
        adapter.launcher("edge")("some-other-image", ["sqlmap"])

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
        ran.return_value.stderr = f"{openstack.EXIT_MARK}0\n"
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
