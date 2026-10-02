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
                   nodes=(Node("fsl-pfsense", "10.31.0.63"), Node("fsl-platform", "10.31.0.195"),
                          Node("fsl-waf", "10.31.0.198")))
    return Shape(segments=origins + (mgmt,), sensors=())

class Edge:
    def __init__(self, holds=None, exit_code=0, sensor="running", logs="10.31.0.195:5140"):
        self.calls = []
        self.sensor = sensor
        self.logs = logs
        self.holds = holds
        self.exit_code = exit_code

    def __call__(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.calls.append((role, argv, stdin))
            holds = self.holds if self.holds is not None else [
                o.subnet.replace("0/24", "1") for o in OS.origins
            ]
            if role != "edge":
                return Ran(self.exit_code, "")
            return Ran(self.exit_code, "fsl-edge wan " + " ".join(holds) + "\n"
                       + f"fsl-edge sensor vtnet0 {self.sensor}\n"
                       + f"fsl-edge logs {self.logs}\n")
        return run

class Groups:
    def __init__(self, rules=()):
        self.group = {"id": "sg-reach", "name": "fsl-reach", "security_group_rules": list(rules)}
        self.calls = []

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        self.calls.append((verb, url, body))
        if verb == "GET":
            return {"security_groups": [{"id": "sg-range", "name": "fsl-range"}, self.group]}
        if verb == "POST":
            made = dict(body["security_group_rule"], id=f"r-{len(self.calls)}")
            self.group["security_group_rules"].append(made)
            return {"security_group_rule": made}
        ident = url.rsplit("/", 1)[1]
        self.group["security_group_rules"] = [
            r for r in self.group["security_group_rules"] if r["id"] != ident]
        return {}

def _adapter(edge, groups=None):
    built = openstack.OpenStack(OS, SPEC, get=groups or Groups(),
                                build=openstack.Build(source=str(ROOT)))
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
    wanted = pfsense.settings(_shape().segments, OS, rules, "10.31.0.195:5140")
    assert stdin == pfsense.playback(wanted, template)
    host, reported = done
    assert host == "fsl-pfsense" and "logs 10.31.0.195:5140" in reported

def test_an_edge_that_does_not_hold_every_origin_gateway_afterwards_is_drift():
    edge = Edge(holds=["73.0.0.1"])

    with pytest.raises(Drifted, match="120.96.0.1"):
        _adapter(edge).configure_edge()

def test_an_edge_whose_playback_failed_is_drift_even_if_it_printed_addresses():
    with pytest.raises(Drifted, match="exit"):
        _adapter(Edge(exit_code=1)).configure_edge()

def test_an_edge_logging_somewhere_else_afterwards_is_drift():
    with pytest.raises(Drifted, match="logs"):
        _adapter(Edge(logs="10.9.9.9:514")).configure_edge()

def test_configuring_the_slot_configures_the_edge_and_the_waf_and_opens_the_collector_to_both():
    edge, groups = Edge(), Groups()

    done = _adapter(edge, groups).configure_slot()

    assert [host for host, _ in done] == ["fsl-pfsense", "fsl-waf", "fsl-platform"]
    heard = {r["remote_ip_prefix"] for r in groups.group["security_group_rules"]}
    assert heard == {"10.31.0.63/32", "10.31.0.198/32"}

def test_the_waf_is_told_to_forward_its_audit_log_to_the_platform_on_management():
    from range import waf

    edge = Edge()
    _adapter(edge).configure_slot()

    (role, argv, stdin), = [call for call in edge.calls if call[0] == "gateway"]
    audit = waf.audit_log((ROOT / waf.MODSECURITY).read_text())
    assert argv == waf.command()
    assert stdin == waf.forwarding(audit, "10.31.0.195", 5140)

def test_a_waf_whose_forwarding_did_not_apply_is_drift():
    class Refusing(Edge):
        def __call__(self, role, segment_id=""):
            if role == "gateway":
                return lambda argv, stdin=None, timeout=60.0: Ran(1, "rsyslogd: error")
            return super().__call__(role, segment_id)

    with pytest.raises(Drifted, match="fsl-waf"):
        _adapter(Refusing()).configure_slot()

def test_an_edge_whose_sensor_is_not_running_afterwards_is_drift():
    with pytest.raises(Drifted, match="sensor"):
        _adapter(Edge(sensor="stopped")).configure_edge()
