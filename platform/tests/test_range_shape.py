import json
from unittest.mock import patch

import pytest

from range.declared import Declaration
from range.docker import Docker
from range.ports import RangeUnavailable, Segment

DECLARED = Declaration(
    segments=(
        Segment(id="edge", name="Internet", origin="Moscow, Russia"),
        Segment(id="estate", name="Application estate"),
        Segment(id="mgmt", name="Management"),
    ),
    roles={"sensor": "fsl-suricata", "gateway": "fsl-waf"},
    watches={"sensor": "gateway"},
)

NETWORKS = [
    {"Name": "fsl_edge",
     "Labels": {"fsl.segment.id": "edge",
                "fsl.origin": "Nowhere at all", "fsl.segment": "Whatever"},
     "IPAM": {"Config": [{"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "5.188.10.4/24"},
         "bbb": {"Name": "fsl-proxy", "IPv4Address": "5.188.10.3/24"},
     }},
    {"Name": "fsl_estate", "Labels": {"fsl.segment.id": "estate"},
     "IPAM": {"Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "172.30.0.3/24"},
         "ccc": {"Name": "fsl-juice-shop", "IPv4Address": "172.30.0.2/24"},
     }},
    {"Name": "fsl_mgmt", "Labels": {"fsl.segment.id": "mgmt"},
     "IPAM": {"Config": [{"Subnet": "172.31.0.0/24", "Gateway": "172.31.0.1"}]},
     "Containers": {
         "ddd": {"Name": "fsl-elasticsearch", "IPv4Address": "172.31.0.2/24"},
     }},
]

MODES = {
    "fsl-waf": "fsl_edge",
    "fsl-proxy": "fsl_edge",
    "fsl-juice-shop": "fsl_estate",
    "fsl-elasticsearch": "fsl_mgmt",
    "fsl-suricata": "container:aaa",
}

class _Run:
    def __init__(self, networks=NETWORKS, modes=MODES, code=0, stderr=""):
        self.argv = []
        self.networks, self.modes, self.code, self.stderr = (
            networks, modes, code, stderr,
        )

    def __call__(self, argv, **kwargs):
        self.argv.append(argv)
        if argv[:3] == ["docker", "network", "ls"]:
            wanted = [
                a.split("=", 2)[2] for a in argv
                if a.startswith("label=fsl.segment.id=")
            ]
            out = "\n".join(
                n["Name"] for n in self.networks
                if not wanted
                or (n.get("Labels") or {}).get("fsl.segment.id") in wanted
            )
        elif argv[:3] == ["docker", "network", "inspect"]:
            out = "\n".join(json.dumps(n) for n in self.networks)
        elif argv[:2] == ["docker", "ps"]:
            out = "\n".join(self.modes)
        else:
            out = "\n".join(f"{name} {mode}" for name, mode in self.modes.items())
        return type("R", (), {"returncode": self.code, "stdout": out,
                              "stderr": self.stderr})()

def describe(**kwargs):
    with patch("range.docker.subprocess.run", _Run(**kwargs)):
        return Docker(DECLARED).describe()

def segment(shape, segment_id):
    return next(s for s in shape.segments if s.id == segment_id)

def test_every_network_of_the_project_is_a_segment():
    assert {s.id for s in describe().segments} == {"edge", "estate", "mgmt"}

def test_a_segment_carries_the_name_the_substrate_knows_it_by():
    assert segment(describe(), "edge").network == "fsl_edge"

def test_a_segment_is_called_what_the_declaration_calls_it():
    assert segment(describe(), "estate").name == "Application estate"

def test_a_segment_nobody_declared_stops_the_picture():
    thin = Declaration(segments=(Segment(id="edge", name="Internet"),))

    with pytest.raises(RangeUnavailable, match="estate"):
        with patch("range.docker.subprocess.run", _Run()):
            Docker(thin).describe()

def test_the_declaration_says_what_a_segment_means_and_the_substrate_does_not():
    edge = segment(describe(), "edge")

    assert (edge.name, edge.origin) == ("Internet", "Moscow, Russia"), (
        "the meaning came off a label the substrate was carrying; Neutron has "
        "no such label to carry"
    )

def test_a_segment_the_declaration_gives_an_origin_is_outside():
    assert segment(describe(), "edge").outside is True
    assert segment(describe(), "estate").outside is False

def test_a_segment_carries_the_addresses_that_are_actually_on_it():
    estate = segment(describe(), "estate")

    assert {n.name: n.address for n in estate.nodes} == {
        "fsl-juice-shop": "172.30.0.2",
        "fsl-waf": "172.30.0.3",
    }
    assert estate.subnet == "172.30.0.0/24"
    assert estate.gateway == "172.30.0.1"

def test_a_sensor_sharing_a_namespace_is_reported_where_it_watches():
    assert [(s.name, s.watches) for s in describe().sensors] == [
        ("fsl-suricata", "fsl-waf"),
    ]

def test_a_substrate_that_cannot_answer_is_an_error_not_an_empty_shape():
    with pytest.raises(RangeUnavailable, match="daemon"):
        describe(code=1, stderr="Cannot connect to the Docker daemon")

def test_a_project_with_no_networks_is_an_error_not_an_empty_shape():
    with pytest.raises(RangeUnavailable):
        describe(networks=[])

def test_reading_the_shape_asks_each_question_once():
    spy = _Run()
    with patch("range.docker.subprocess.run", spy):
        Docker(DECLARED).describe()

    assert len(spy.argv) == 4, (
        f"one describe() cost {len(spy.argv)} round trips: "
        f"{[' '.join(a[:3]) for a in spy.argv]}"
    )

def test_a_sensor_standing_on_a_segment_is_not_one_of_its_participants():
    from range.declared import Declaration, Segment
    from range.ports import Node, Shape

    import topology

    shape = Shape(
        segments=(
            Segment(
                id="edge", name="Internet", origin="Moscow, Russia",
                nodes=(Node(name="fsl-kali", address="5.188.10.2"),
                       Node(name="fsl-suricata", address="5.188.10.9")),
            ),
        ),
        sensors=(),
    )

    picture = topology.shape(shape, Declaration(roles={"sensor": "fsl-suricata"}))
    edge = picture["segments"][0]
    watching = [n for n in edge["nodes"] if n.get("watches")]

    assert [n["name"] for n in edge["nodes"] if not n.get("watches")] == ["fsl-kali"], (
        "the sensor is drawn as a host on the segment, so an operator reads it "
        "as something traffic can reach. On Docker it owns no port and never "
        "appeared; on Nova it is an instance and appears on every segment"
    )
    assert [n["name"] for n in watching] == ["fsl-suricata"]

def test_a_host_that_is_not_the_sensor_is_left_alone():
    from range.declared import Declaration, Segment
    from range.ports import Node, Shape

    import topology

    shape = Shape(
        segments=(Segment(id="estate", name="Application estate",
                          nodes=(Node(name="fsl-juice-shop", address="172.30.0.2"),)),),
        sensors=(),
    )

    picture = topology.shape(shape, Declaration(roles={"sensor": "fsl-suricata"}))

    assert not picture["segments"][0]["nodes"][0].get("watches")

def test_a_segment_nobody_declared_is_reported_not_invented():
    from range.declared import Declaration

    found = Declaration(segments=(), roles={})

    with pytest.raises(RangeUnavailable, match="ghost"):
        found.segment("ghost")

def test_a_declared_segment_still_comes_back():
    from range.declared import Declaration
    from range.ports import Segment

    found = Declaration(segments=(Segment(id="edge", name="Internet"),))

    assert found.segment("edge").name == "Internet"

def test_the_adapter_says_which_network_it_could_not_place():
    from range.declared import Declaration
    from range.docker import Docker

    adapter = Docker(Declaration(segments=(), roles={}))

    with pytest.raises(RangeUnavailable, match="edge"):
        with patch("range.docker.subprocess.run", _Run()):
            adapter.describe()

def test_a_network_carrying_two_subnets_is_not_quietly_halved():
    many = [dict(NETWORKS[0], IPAM={"Config": [
        {"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"},
        {"Subnet": "fd00:5:188:10::/64", "Gateway": "fd00:5:188:10::1"},
    ]})] + NETWORKS[1:]

    with pytest.raises(RangeUnavailable, match="edge"):
        with patch("range.docker.subprocess.run", _Run(networks=many)):
            Docker(DECLARED).describe()

def test_a_network_with_one_subnet_is_unaffected():
    assert segment(describe(), "edge").subnet == "5.188.10.0/24"

def test_a_segment_is_bound_by_the_mark_it_carries_not_by_its_name():
    renamed = [NETWORKS[0], dict(NETWORKS[1], Name="corp-estate"), NETWORKS[2]]

    with patch("range.docker.subprocess.run", _Run(networks=renamed)):
        shape = Docker(DECLARED).describe()

    assert segment(shape, "estate").network == "corp-estate", (
        "the id was cut off the front of the network name, so a range whose "
        "networks are not named after the platform has no segments at all"
    )

def test_a_network_the_range_does_not_mark_is_not_part_of_it():
    extra = NETWORKS + [{"Name": "fsl_scratch", "Labels": {},
                         "IPAM": {"Config": []}, "Containers": {}}]

    with patch("range.docker.subprocess.run", _Run(networks=extra)):
        shape = Docker(DECLARED).describe()

    assert {s.id for s in shape.segments} == {"edge", "estate", "mgmt"}, (
        "a substrate holds networks that are not the range - on Neutron every "
        "tenant network comes back - and an unmarked one was drawn as a segment"
    )

def test_two_networks_claiming_the_same_segment_are_refused():
    doubled = NETWORKS + [dict(NETWORKS[1], Name="fsl_estate_old")]

    with pytest.raises(RangeUnavailable, match="both carry"):
        with patch("range.docker.subprocess.run", _Run(networks=doubled)):
            Docker(DECLARED).describe()

def test_what_the_project_is_called_no_longer_decides_any_segment_id():
    lab = [dict(network, Name="fsl_lab_" + network["Labels"]["fsl.segment.id"])
           for network in NETWORKS]

    with patch("range.docker.subprocess.run", _Run(networks=lab)):
        shape = Docker(DECLARED, project="fsl_lab").describe()

    assert {s.id for s in shape.segments} == {"edge", "estate", "mgmt"}, (
        "the id was cut off the front of the name by splitting on the first "
        "underscore, so a project called fsl_lab swallowed part of itself and "
        "every segment came back wrong"
    )

def test_a_tool_is_launched_on_the_segment_it_was_given():
    spy = _Run()
    with patch("range.docker.subprocess.run", spy):
        Docker(DECLARED).launcher("estate")("fsl-kali", ["sqlmap", "-u", "x"])

    started = spy.argv[-1]

    assert started[:3] == ["docker", "run", "--rm"]
    assert started[started.index("--network") + 1] == "fsl_estate"
    assert started[-4:] == ["fsl-kali", "sqlmap", "-u", "x"]

def test_a_tool_on_a_segment_nobody_marked_is_refused():
    spy = _Run(networks=[])
    with pytest.raises(RangeUnavailable, match="dmz"):
        with patch("range.docker.subprocess.run", spy):
            Docker(DECLARED).launcher("dmz")("fsl-kali", ["sqlmap"])

def test_what_the_sensor_watches_is_declared_and_not_guessed():
    quiet = Declaration(
        segments=DECLARED.segments,
        roles=DECLARED.roles,
        watches={},
    )

    with patch("range.docker.subprocess.run", _Run()):
        shape = Docker(quiet).describe()

    assert shape.sensors == (), (
        "the adapter found a sensor nothing declared, by reading a Docker fact "
        "- NetworkMode: container:<id> - that Neutron has no equivalent of"
    )

def test_a_sensor_that_is_not_where_it_was_declared_to_be_is_refused():
    elsewhere = dict(MODES, **{"fsl-suricata": "fsl_mgmt"})

    with pytest.raises(RangeUnavailable, match="fsl-waf"):
        with patch("range.docker.subprocess.run", _Run(modes=elsewhere)):
            Docker(DECLARED).describe()

def test_a_declared_sensor_the_substrate_confirms_is_reported():
    on_the_target = Declaration(
        segments=DECLARED.segments,
        roles=dict(DECLARED.roles, target="fsl-juice-shop"),
        watches={"sensor": "target"},
    )
    beside_the_target = dict(MODES, **{"fsl-suricata": "container:ccc"})

    with patch("range.docker.subprocess.run", _Run(modes=beside_the_target)):
        shape = Docker(on_the_target).describe()

    assert [(s.name, s.watches) for s in shape.sensors] == [
        ("fsl-suricata", "fsl-juice-shop"),
    ]

def test_the_segments_are_known_while_the_sensor_is_not_where_it_should_be():
    elsewhere = dict(MODES, **{"fsl-suricata": "fsl_mgmt"})

    with patch("range.docker.subprocess.run", _Run(modes=elsewhere)):
        listed = Docker(DECLARED).segments()

    assert {s.id for s in listed} == {s.id for s in DECLARED.segments}, (
        "a stopped or misplaced sensor made the whole range unreadable, and "
        "everything that only needs to know who stands where failed with it"
    )
