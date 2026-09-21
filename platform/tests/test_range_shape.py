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
    ),
)

NETWORKS = [
    {"Name": "fsl_edge",
     "Labels": {"fsl.origin": "Nowhere at all", "fsl.segment": "Whatever"},
     "IPAM": {"Config": [{"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "5.188.10.4/24"},
         "bbb": {"Name": "fsl-proxy", "IPv4Address": "5.188.10.3/24"},
     }},
    {"Name": "fsl_estate", "Labels": {},
     "IPAM": {"Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "172.30.0.3/24"},
         "ccc": {"Name": "fsl-juice-shop", "IPv4Address": "172.30.0.2/24"},
     }},
    {"Name": "fsl_mgmt", "Labels": {},
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
            out = "\n".join(n["Name"] for n in self.networks)
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

def test_a_segment_nobody_declared_falls_back_to_its_own_name():
    assert segment(describe(), "mgmt").name == "mgmt"
    assert segment(describe(), "mgmt").origin == ""

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
