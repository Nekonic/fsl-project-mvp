import pathlib

import pytest

from range import cloud, declared, openstack, opnsense, wargame_host
from range.ports import Drifted, Node, Ran, RangeUnavailable, Segment, Shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSIDE = cloud.read(cloud.EXAMPLE).inside
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlatformKey fsl-platform"
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
                nodes=(Node("fsl-edge", o.subnet.replace("0/24", "1")),))
        for o in OS.origins
    )
    estate = Segment(id="estate", name="Estate", subnet="10.30.0.0/24", gateway="10.30.0.1",
                     nodes=(Node("fsl-waf", "10.30.0.198"), Node("fsl-wargame-host", "10.30.0.63")))
    mgmt = Segment(id="mgmt", name="Management", subnet="10.31.0.0/24",
                   nodes=(Node("fsl-edge", "10.31.0.63"), Node("fsl-platform", "10.31.0.195"),
                          Node("fsl-waf", "10.31.0.198"), Node("fsl-wargame-host", "10.31.0.107")))
    return Shape(segments=origins + (estate, mgmt), sensors=())

class Edge:
    def __init__(self, holds=None, exit_code=0, sensor="running", logs="10.31.0.195:5140",
                 wanrule=1, reboots=True, unreachable=0):
        self.calls = []
        self.sensor = sensor
        self.logs = logs
        self.wanrule = wanrule
        self.holds = holds
        self.exit_code = exit_code
        self.reboots = reboots
        self.unreachable = unreachable

    def __call__(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.calls.append((role, argv, stdin))
            if role != "edge":
                return Ran(self.exit_code, "")
            if argv == opnsense.command():
                return Ran(self.exit_code, "fsl-edge booted 100\nfsl-edge rebooting\n")
            if self.unreachable:
                self.unreachable -= 1
                raise RangeUnavailable("fsl-edge at 10.31.0.63 never reported the command finishing")
            holds = self.holds if self.holds is not None else [
                o.subnet.replace("0/24", "1") for o in OS.origins
            ]
            return Ran(self.exit_code, f"fsl-edge booted {200 if self.reboots else 100}\n"
                       + "fsl-edge wan " + " ".join(holds) + "\n"
                       + f"fsl-edge sensor vtnet0 {self.sensor}\n"
                       + f"fsl-edge logs {self.logs}\n"
                       + f"fsl-edge wanrule {self.wanrule}\n")
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
                                build=openstack.Build(source=str(ROOT), inside=INSIDE, mtu=1450))
    built._shape = _shape()
    built.runner = edge
    built._public_key = lambda make=False: KEY
    return built

@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(openstack.time, "sleep", lambda seconds: None)

def test_configuring_the_edge_stages_its_config_over_management_and_reboots_it():
    edge = Edge()

    done = _adapter(edge).configure_edge()

    (role, argv, stdin), *after = edge.calls
    assert role == "edge" and argv == opnsense.command()
    wanted = opnsense.settings(_shape().segments, ("10.31.0.195", 5140), INSIDE, 1450, KEY,
                               management=_adapter(Edge()).address("edge"), front="10.30.0.198")
    assert wanted["mgmt"]["address"]
    assert stdin == opnsense.playback(
        opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted),
        (ROOT / opnsense.INCLUDE).read_text(),
        (ROOT / opnsense.RULES).read_text(),
        (ROOT / opnsense.SCRIPT).read_text(),
    )
    assert [call[1] for call in after] == [opnsense.verify()]
    host, reported = done
    assert host == "fsl-edge" and "logs 10.31.0.195:5140" in reported

def test_the_edge_is_read_back_only_once_it_has_rebooted():
    edge = Edge(unreachable=3)

    _adapter(edge).configure_edge()

    assert len([call for call in edge.calls if call[1] == opnsense.verify()]) == 4

def test_an_edge_that_never_reboots_is_drift(monkeypatch):
    clock = iter(range(0, 100000, 100))
    monkeypatch.setattr(openstack.time, "monotonic", lambda: next(clock))

    with pytest.raises(Drifted, match="did not come back from its reboot"):
        _adapter(Edge(reboots=False)).configure_edge()

def test_an_edge_that_refused_its_configuration_is_not_waited_for():
    edge = Edge(exit_code=1)

    with pytest.raises(Drifted, match="did not take its configuration"):
        _adapter(edge).configure_edge()

    assert len(edge.calls) == 1

def test_an_edge_that_does_not_hold_every_origin_gateway_afterwards_is_drift():
    edge = Edge(holds=["73.0.0.1"])

    with pytest.raises(Drifted, match="120.96.0.1"):
        _adapter(edge).configure_edge()

def test_an_edge_logging_somewhere_else_afterwards_is_drift():
    with pytest.raises(Drifted, match="logs"):
        _adapter(Edge(logs="10.9.9.9:514")).configure_edge()

def test_configuring_the_slot_configures_the_edge_and_the_waf_opens_the_collector_and_starts_the_wargames():
    edge, groups = Edge(), Groups()

    done = _adapter(edge, groups).configure_slot()

    assert [host for host, _ in done] == [
        "fsl-edge", "fsl-waf", "fsl-platform", "fsl-wargame-host", "fsl-wargame-host",
        "fsl-wargame-host",
    ]
    assert [argv for role, argv, _ in edge.calls if role == "wargames"][:2] == [
        wargame_host.up(wargame) for wargame in OS.hosts["fsl-wargame-host"].wargames
    ], "a rebuilt wargame host holds the images and no containers; configure starts them"
    heard = {r["remote_ip_prefix"] for r in groups.group["security_group_rules"]}
    assert heard == {"10.31.0.63/32", "10.31.0.198/32", "10.31.0.107/32"}, (
        "the wargame host ships its sensor's eve log to the collector as the edge does"
    )

def test_the_wargame_host_starts_its_sensor_on_the_interface_holding_its_estate_address():
    edge = Edge()

    _adapter(edge).configure_slot()

    started = [argv for role, argv, _ in edge.calls if role == "wargames"]
    assert wargame_host.sensor_up("10.30.0.63") in started
    assert started.index(wargame_host.sensor_up("10.30.0.63")) > started.index(
        wargame_host.up("corp")), "the sensor starts once the wargames it watches answer"
    assert "show to 10.30.0.63" in wargame_host.sensor_up("10.30.0.63")[2]

def test_the_wargame_host_forwards_its_sensor_eve_log_to_the_collector_tagged_suricata():
    from range import waf

    edge = Edge()
    _adapter(edge).configure_slot()

    forwarded = [(argv, stdin) for role, argv, stdin in edge.calls
                 if role == "wargames" and argv == waf.command("suricata")]
    assert forwarded == [(waf.command("suricata"), waf.forwarding(
        "/var/log/suricata/eve.json", "10.31.0.195", 5140, "suricata"))], (
        "the collector decodes a syslog line as Suricata by its program name"
    )

def test_a_sensor_that_does_not_come_up_healthy_is_drift():
    class Refusing(Edge):
        def __call__(self, role, segment_id=""):
            inner = super().__call__(role, segment_id)
            def run(argv, stdin=None, timeout=60.0):
                if argv == wargame_host.sensor_up("10.30.0.63"):
                    return Ran(1, "container suricata is unhealthy")
                return inner(argv, stdin, timeout)
            return run

    with pytest.raises(Drifted, match="sensor"):
        _adapter(Refusing()).configure_slot()

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

def test_an_edge_whose_wan_pass_rule_did_not_load_into_pf_is_drift():
    with pytest.raises(Drifted, match="wan rule|pf"):
        _adapter(Edge(wanrule=0)).configure_edge()

def test_an_edge_whose_sensor_starts_after_ssh_answers_is_waited_for():
    class LateSensor(Edge):
        def __call__(self, role, segment_id=""):
            inner = super().__call__(role, segment_id)
            def run(argv, stdin=None, timeout=60.0):
                if argv == opnsense.verify():
                    reads = len([c for c in self.calls if c[1] == opnsense.verify()])
                    self.sensor = "running" if reads >= 2 else "stopped"
                return inner(argv, stdin, timeout)
            return run

    edge = LateSensor()

    host, _ = _adapter(edge).configure_edge()

    assert host == "fsl-edge"
    assert len([call for call in edge.calls if call[1] == opnsense.verify()]) == 3
