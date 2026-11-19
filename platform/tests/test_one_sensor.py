import pathlib

from range import declared, openstack, sandbox
from tests.test_rules_port import RELOAD

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXTRA = (("second-sensor", "/var/lib/suricata/rules/local.rules", RELOAD),)

class Standing:
    def __init__(self, edge, estate):
        self.sensors = {"sensor": edge, "second-sensor": estate}

    def __call__(self):
        return self

    def runner(self, role, segment_id=""):
        return self.sensors[role]

def test_the_one_sensor_stands_inline_behind_the_waf_on_the_slot_s_infra_node():
    for wargame in sandbox.wargames(ROOT):
        definition = sandbox.read(ROOT, wargame)
        sensor = definition.filling("sensor")
        legs = [port for port in definition.ports if port.device == sensor.name]

        assert sensor.node == "cr-infra" and {port.lan for port in legs} == {"web-outer", "web-inner"}
        assert all(port.ids for port in legs), "the sensor's legs carry no address, so nothing reaches it on them"


def test_the_sensor_starts_on_the_shipped_baseline_rules():
    stack = declared.read()
    entry = stack.hosts[stack.roles["sensor"]]

    assert entry.rules == "/var/lib/suricata/rules/local.rules"
    assert (ROOT / openstack.BASELINE_RULES).is_file(), (
        "a slot's configure seeds the sensor from local.rules; the ready check reads the sensor's rules against it")


