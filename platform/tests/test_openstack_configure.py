import pathlib

import pytest

from range import declared, openstack, pfsense
from range.ports import Drifted, Node, Ran, Segment, Shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
OS = declared.read(flavor="openstack")
SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="fsl",
    user="fsl", ssh_user="ubuntu", ssh_key="/keys/fsl",
)

def _shape():
    origins = tuple(
        Segment(id=o.id, name=o.label, origin=o.label, subnet=o.subnet,
                gateway=o.subnet.replace("0/24", "1"),
                nodes=(Node("fsl-pfsense", o.subnet.replace("0/24", "1")),))
        for o in OS.origins
    )
    mgmt = Segment(id="mgmt", name="Management", subnet="10.31.0.0/24",
                   nodes=(Node("fsl-pfsense", "10.31.0.63"),))
    return Shape(segments=origins + (mgmt,), sensors=())

class Edge:
    def __init__(self, holds=None, exit_code=0, sensor="running"):
        self.calls = []
        self.sensor = sensor
        self.holds = holds
        self.exit_code = exit_code

    def __call__(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.calls.append((role, argv, stdin))
            holds = self.holds if self.holds is not None else [
                o.subnet.replace("0/24", "1") for o in OS.origins
            ]
            return Ran(self.exit_code, "fsl-edge wan " + " ".join(holds) + "\n"
                       + f"fsl-edge sensor vtnet0 {self.sensor}\n")
        return run

def _adapter(edge):
    built = openstack.OpenStack(OS, SPEC, get=None, build=openstack.Build(source=str(ROOT)))
    built._shape = _shape()
    built.runner = edge
    return built

def test_configuring_the_edge_plays_the_static_script_back_on_it_over_management():
    edge = Edge()

    done = _adapter(edge).configure_edge()

    (role, argv, stdin), = edge.calls
    assert role == "edge" and argv == pfsense.command()
    template = (ROOT / pfsense.TEMPLATE).read_text()
    rules = (ROOT / pfsense.RULES).read_text()
    assert stdin == pfsense.playback(pfsense.settings(_shape().segments, OS, rules), template)
    assert done == ("fsl-pfsense", tuple(o.subnet.replace("0/24", "1") for o in OS.origins))

def test_an_edge_that_does_not_hold_every_origin_gateway_afterwards_is_drift():
    edge = Edge(holds=["73.0.0.1"])

    with pytest.raises(Drifted, match="120.96.0.1"):
        _adapter(edge).configure_edge()

def test_an_edge_whose_playback_failed_is_drift_even_if_it_printed_addresses():
    with pytest.raises(Drifted, match="exit"):
        _adapter(Edge(exit_code=1)).configure_edge()

def test_configuring_the_slot_reports_each_host_it_configured():
    edge = Edge()

    done = _adapter(edge).configure_slot()

    assert done[0][0] == "fsl-pfsense"

def test_an_edge_whose_sensor_is_not_running_afterwards_is_drift():
    with pytest.raises(Drifted, match="sensor"):
        _adapter(Edge(sensor="stopped")).configure_edge()
