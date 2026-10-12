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
    assert [call[1] for call in after] == [
        opnsense.verify(),
        opnsense.record(opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted)),
    ], "once settled, the edge records the config it booted into so a reset can check it"
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

class Meeting(Edge):
    def __init__(self, meeting, **kwargs):
        super().__init__(**kwargs)
        self.meeting = meeting

    def __call__(self, role, segment_id=""):
        inner = super().__call__(role, segment_id)
        def run(argv, stdin=None, timeout=60.0):
            if argv in (opnsense.command(), wargame_host.up("board")):
                self.meeting.wait()
            return inner(argv, stdin, timeout)
        return run

def test_the_wargames_start_while_the_edge_reboots():
    import threading

    edge = Meeting(threading.Barrier(2, timeout=5))

    done = _adapter(edge).configure_slot()

    assert [host for host, _ in done][:2] == ["fsl-edge", "fsl-waf"], (
        "the steps run side by side and still report in the order they are declared"
    )

def test_a_step_that_fails_beside_others_fails_the_configure_with_its_own_reason():
    import threading

    edge = Meeting(threading.Barrier(2, timeout=5), sensor="stopped")

    with pytest.raises(Drifted, match="its sensor is not running"):
        _adapter(edge).configure_slot()

    started = [argv for role, argv, _ in edge.calls if role == "wargames"]
    assert wargame_host.sensor_up("10.30.0.63") in started, (
        "the wargame host's steps ran to the end while the edge failed beside them"
    )

class LateWargameHost(Edge):
    def __init__(self, unanswered, **kwargs):
        super().__init__(**kwargs)
        self.unanswered = unanswered

    def __call__(self, role, segment_id=""):
        inner = super().__call__(role, segment_id)
        def run(argv, stdin=None, timeout=60.0):
            if role == "wargames" and self.unanswered:
                self.unanswered -= 1
                self.calls.append((role, argv, stdin))
                raise RangeUnavailable("fsl-wargame-host at 10.31.0.107 refused the connection")
            return inner(argv, stdin, timeout)
        return run

def test_a_host_that_does_not_answer_yet_is_waited_for_without_rebooting_the_edge_again():
    edge = LateWargameHost(unanswered=3)

    done = _adapter(edge).configure_slot()

    assert "fsl-wargame-host" in [host for host, _ in done]
    assert len([call for call in edge.calls if call[1] == opnsense.command()]) == 1, (
        "the rebuilt wargame host took longer to answer ssh than the edge took to "
        "configure, and the whole configure was retried, rebooting the edge twice"
    )

def test_a_host_that_never_answers_still_fails_the_configure():
    edge = LateWargameHost(unanswered=openstack.HOST_READS)

    with pytest.raises(RangeUnavailable, match="refused the connection"):
        _adapter(edge).configure_slot()


class ResetsInPlace(Edge):
    def __init__(self, said="fsl-edge reset\n", **kwargs):
        super().__init__(**kwargs)
        self.said = said

    def __call__(self, role, segment_id=""):
        inner = super().__call__(role, segment_id)
        def run(argv, stdin=None, timeout=60.0):
            if role == "edge" and argv == opnsense.command() and _in_place(stdin):
                self.calls.append((role, argv, stdin))
                return Ran(self.exit_code, self.said)
            return inner(argv, stdin, timeout)
        return run

def _in_place(stdin):
    return bool(stdin) and stdin.endswith(f'echo "{opnsense.RESET}"\n')

def _reinstalls(edge):
    return [call for call in edge.calls
            if call[1] == opnsense.command() and not _in_place(call[2])]

def test_resetting_the_edge_in_place_restarts_its_sensor_without_reinstalling_or_rebooting():
    edge = ResetsInPlace()

    host, reported = _adapter(edge).reset_edge()

    assert host == "fsl-edge" and "reset in place" in reported
    assert _reinstalls(edge) == [], (
        "the edge's config is the same rendered file every session, and reinstalling "
        "it means a reboot that sets the length of every reset"
    )
    (_, _, stdin), verified = edge.calls
    assert verified[1] == opnsense.verify()
    assert "configctl ids restart" in stdin and "configctl filter reload" in stdin
    assert (ROOT / opnsense.RULES).read_text() in stdin, (
        "the session may change fsl.rules, so the reset puts the baseline back"
    )

def test_the_in_place_reset_compares_every_installed_file_by_its_hash():
    edge = ResetsInPlace()

    _adapter(edge).reset_edge()

    stdin = edge.calls[0][2]
    wanted = opnsense.settings(_shape().segments, ("10.31.0.195", 5140), INSIDE, 1450, KEY,
                               management=_adapter(Edge()).address("edge"), front="10.30.0.198")
    config = opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted)
    for content in (config, (ROOT / opnsense.INCLUDE).read_text(), (ROOT / opnsense.RULES).read_text()):
        assert opnsense.fingerprint(content) in stdin
    assert opnsense.SETTLED in stdin and opnsense.INSTALLED["config"] in stdin

def test_the_in_place_reset_drops_the_range_states_and_keeps_the_management_ones():
    edge = ResetsInPlace()

    _adapter(edge).reset_edge()

    stdin = edge.calls[0][2]
    assert "pfctl -k 10.30.0.0/24" in stdin and "pfctl -k 0.0.0.0/0 -k 73.0.0.0/24" in stdin
    assert "10.31.0.0/24" not in stdin and "-F state" not in stdin, (
        "flushing every state drops the platform's own ssh session to the edge mid-reset"
    )

@pytest.mark.parametrize("said, why", [
    ("fsl-edge drifted config\n", "config drifted"),
    ("fsl-edge drifted include rules\n", "include, rules drifted"),
    ("fsl-edge drifted sensor\n", "sensor drifted"),
])
def test_an_edge_whose_files_do_not_match_is_reinstalled_and_rebooted(said, why):
    edge = ResetsInPlace(said=said)

    host, reported = _adapter(edge).reset_edge()

    assert len(_reinstalls(edge)) == 1, "a mismatch falls back to the install and reboot"
    assert host == "fsl-edge"
    assert f"reinstalled and rebooted: {why}" in reported
    assert edge.calls[-1][1][2].endswith(f"> {opnsense.SETTLED}")

def test_an_edge_that_does_not_hold_its_configuration_after_the_reset_is_reinstalled():
    class LosesItsRule(ResetsInPlace):
        def __call__(self, role, segment_id=""):
            self.wanrule = 0 if not _reinstalls(self) else 1
            return super().__call__(role, segment_id)

    edge = LosesItsRule()

    _, reported = _adapter(edge).reset_edge()

    assert len(_reinstalls(edge)) == 1
    assert any("did not hold its configuration" in line for line in reported)

def test_resetting_in_place_clears_the_wargames_and_starts_them_fresh_on_the_same_vm():
    edge, groups = ResetsInPlace(), Groups()

    done = _adapter(edge, groups).reset_in_place()

    on_the_host = [(argv, stdin) for role, argv, stdin in edge.calls if role == "wargames"]
    cleared = wargame_host.cleared(OS.hosts["fsl-wargame-host"].wargames,
                                   ("/var/log/suricata/eve.json",), True)
    assert on_the_host[0] == (cleared, (ROOT / wargame_host.BASELINE_RULES).read_text())
    assert [argv for argv, _ in on_the_host[1:3]] == [
        wargame_host.up(wargame) for wargame in OS.hosts["fsl-wargame-host"].wargames
    ]
    assert wargame_host.sensor_up("10.30.0.63") in [argv for argv, _ in on_the_host]
    assert {host for host, _ in done} == {"fsl-edge", "fsl-platform", "fsl-wargame-host"}
    assert not [role for role, _, _ in edge.calls if role == "gateway"], (
        "the waf is rebuilt from its image and configured once Nova has it back"
    )

def test_the_rebuilt_vms_are_configured_by_their_own_steps_only():
    edge = ResetsInPlace()
    adapter = _adapter(edge)
    adapter._read = _shape

    done = adapter.configure_rebuilt(["fsl-kali", "fsl-waf"])

    assert [host for host, _ in done] == ["fsl-waf"]
    assert {role for role, _, _ in edge.calls} == {"gateway"}

class Nova:
    def __init__(self):
        self.calls = []

    def __call__(self, call, body=None):
        self.calls.append((call, body))
        return {}

def _standing(adapter):
    from range import slot

    standing = (("fsl-waf", "srv-waf", "ACTIVE"), ("fsl-edge", "srv-edge", "ACTIVE"),
                ("fsl-kali", "srv-kali", "ACTIVE"), ("fsl-wargame-host", "srv-wg", "ACTIVE"))
    ready = {host: f"img-{host}" for host, _, _ in standing}
    adapter._slot = lambda: (slot.Plan(standing=standing), {}, [], [], [], ready)
    return adapter

def test_a_close_rebuilds_only_the_vms_that_hold_a_shell():
    nova = Nova()
    adapter = _standing(_adapter(Edge(), nova))

    rebuilt = adapter.reset_slot()

    assert rebuilt == [("fsl-waf", "srv-waf"), ("fsl-kali", "srv-kali")]
    assert [call for call, _ in nova.calls] == [
        "POST http://nova:8774/v2.1/servers/srv-waf/action",
        "POST http://nova:8774/v2.1/servers/srv-kali/action",
    ], "the edge and the wargame host reset in place; Kali and the WAF hand out a shell"

def test_rebuilding_the_slot_by_hand_still_rebuilds_every_vm():
    nova = Nova()
    adapter = _standing(_adapter(Edge(), nova))

    rebuilt = adapter.rebuild_slot()

    assert [host for host, _ in rebuilt] == ["fsl-waf", "fsl-edge", "fsl-kali", "fsl-wargame-host"]
    assert len(nova.calls) == 4

def test_the_rebuilt_vms_are_configured_from_a_fresh_read_of_the_cloud():
    edge = ResetsInPlace()
    adapter = _adapter(edge)
    reads = []
    adapter._read = lambda: reads.append(1) or _shape()

    adapter.configure_rebuilt(["fsl-waf"])

    assert reads == [1], (
        "the shape read while Nova rebuilt the WAF carries its old launch time, so ssh "
        "checked the rebuilt VM's new host key against the old one and never got in"
    )
