import json
from unittest.mock import patch

import pytest

from range.declared import Declaration
from range.docker import Docker
from range.ports import RangeUnavailable, Segment

DECLARED = Declaration(
    segments=(
        Segment(id="ru", name="Internet", origin="Russia"),
        Segment(id="estate", name="Application estate"),
        Segment(id="mgmt", name="Management"),
    ),
    roles={"sensor": "fsl-suricata", "gateway": "fsl-waf"},
    watches={"sensor": "gateway"},
)

NETWORKS = [
    {"Name": "fsl_edge",
     "Labels": {"fsl.segment.id": "ru",
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
    def __init__(self, networks=NETWORKS, modes=MODES, code=0, stderr="",
                 project="fsl", session="fsl-1"):
        self.argv = []
        self.networks, self.modes, self.code, self.stderr = (
            networks, modes, code, stderr,
        )
        self.project, self.session = project, session

    def __call__(self, argv, **kwargs):
        self.argv.append(argv)
        if argv[:3] == ["docker", "network", "ls"]:
            wanted = [
                a.split("=", 2)[2] for a in argv
                if a.startswith("label=fsl.segment.id=")
            ]
            out = "\n".join(
                f"{n['Name']} "
                f"{(n.get('Labels') or {}).get('com.docker.compose.project', self.project)}"
                for n in self.networks
                if not wanted
                or (n.get("Labels") or {}).get("fsl.segment.id") in wanted
            )
        elif argv[:3] == ["docker", "network", "inspect"]:
            out = "\n".join(json.dumps(n) for n in self.networks)
        elif argv[:2] == ["docker", "ps"]:
            service = next(
                a.split("=", 2)[2] for a in argv
                if a.startswith("label=com.docker.compose.service=")
            )
            out = "\n".join(
                f"{name} {self.session}" for name in self.modes
                if name.removeprefix("fsl-").removeprefix("wg-") == service
            )
        else:
            out = "\n".join(f"{name} {mode}" for name, mode in self.modes.items())
        return type("R", (), {"returncode": self.code, "stdout": out,
                              "stderr": self.stderr})()

def describe(**kwargs):
    with patch("range.docker.subprocess.run", _Run(**kwargs)):
        return Docker(DECLARED).describe()

def segment(shape, segment_id):
    return next(s for s in shape.segments if s.id == segment_id)

def test_every_marked_network_is_a_segment_named_by_the_declaration_with_what_is_on_it():
    shape = describe()
    edge, estate = segment(shape, "ru"), segment(shape, "estate")

    assert {s.id for s in shape.segments} == {"ru", "estate", "mgmt"}
    assert (edge.network, edge.subnet, edge.outside) == ("fsl_edge", "5.188.10.0/24", True)
    assert (edge.name, edge.origin) == ("Internet", "Russia"), (
        "the meaning came off a label the substrate was carrying; Neutron has "
        "no such label to carry"
    )
    assert (estate.name, estate.outside) == ("Application estate", False)
    assert {n.name: n.address for n in estate.nodes} == {
        "fsl-juice-shop": "172.30.0.2",
        "fsl-waf": "172.30.0.3",
    }
    assert (estate.subnet, estate.gateway) == ("172.30.0.0/24", "172.30.0.1")

def test_a_segment_nobody_declared_stops_the_picture():
    thin = Declaration(segments=(Segment(id="ru", name="Internet"),))

    with pytest.raises(RangeUnavailable, match="estate"):
        with patch("range.docker.subprocess.run", _Run()):
            Docker(thin).describe()

def test_a_substrate_that_cannot_answer_is_an_error_not_an_empty_shape():
    with pytest.raises(RangeUnavailable, match="daemon"):
        describe(code=1, stderr="Cannot connect to the Docker daemon")
    with pytest.raises(RangeUnavailable):
        describe(networks=[])

def test_a_sensor_standing_on_a_segment_is_not_one_of_its_participants():
    from range.declared import Declaration, Segment
    from range.ports import Node, Shape

    import topology

    shape = Shape(
        segments=(
            Segment(
                id="ru", name="Internet", origin="Russia",
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

def test_a_network_carrying_two_subnets_is_not_quietly_halved():
    many = [dict(NETWORKS[0], IPAM={"Config": [
        {"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"},
        {"Subnet": "fd00:5:188:10::/64", "Gateway": "fd00:5:188:10::1"},
    ]})] + NETWORKS[1:]

    with pytest.raises(RangeUnavailable, match="edge"):
        with patch("range.docker.subprocess.run", _Run(networks=many)):
            Docker(DECLARED).describe()

def test_a_segment_is_bound_by_the_mark_it_carries_not_by_its_name():
    renamed = [NETWORKS[0], dict(NETWORKS[1], Name="corp-estate"), NETWORKS[2]]
    lab = [dict(network, Name="fsl_lab_" + network["Labels"]["fsl.segment.id"])
           for network in NETWORKS]

    with patch("range.docker.subprocess.run", _Run(networks=renamed)):
        shape = Docker(DECLARED).describe()
    with patch("range.docker.subprocess.run", _Run(networks=lab, project="fsl_lab")):
        lab_shape = Docker(DECLARED, project="fsl_lab").describe()

    assert segment(shape, "estate").network == "corp-estate", (
        "the id was cut off the front of the network name, so a range whose "
        "networks are not named after the platform has no segments at all"
    )
    assert {s.id for s in lab_shape.segments} == {"ru", "estate", "mgmt"}, (
        "the id was cut off the front of the name by splitting on the first "
        "underscore, so a project called fsl_lab swallowed part of itself and "
        "every segment came back wrong"
    )

def test_a_network_the_range_does_not_mark_is_not_part_of_it():
    extra = NETWORKS + [{"Name": "fsl_scratch", "Labels": {},
                         "IPAM": {"Config": []}, "Containers": {}}]

    with patch("range.docker.subprocess.run", _Run(networks=extra)):
        shape = Docker(DECLARED).describe()

    assert {s.id for s in shape.segments} == {"ru", "estate", "mgmt"}, (
        "a substrate holds networks that are not the range - on Neutron every "
        "tenant network comes back - and an unmarked one was drawn as a segment"
    )

def test_two_networks_claiming_the_same_segment_are_refused():
    doubled = NETWORKS + [dict(NETWORKS[1], Name="fsl_estate_old")]

    with pytest.raises(RangeUnavailable, match="both carry"):
        with patch("range.docker.subprocess.run", _Run(networks=doubled)):
            Docker(DECLARED).describe()

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
