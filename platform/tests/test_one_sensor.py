import pathlib

from sandbox import definitions as declaration
from sandbox import openstack, stack_plan

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_one_sensor_stands_inline_behind_the_waf_on_the_slot_s_infra_node():
    for wargame in stack_plan.wargames(ROOT):
        definition = stack_plan.read(ROOT, wargame)
        sensor = definition.filling("sensor")
        legs = [port for port in definition.ports if port.device == sensor.name]

        assert sensor.node == "cr-infra" and {port.lan for port in legs} == {"web-outer", "web-inner"}
        assert all(port.ids for port in legs), "the sensor's legs carry no address, so nothing reaches it on them"


def test_the_sensor_starts_on_the_shipped_baseline_rules():
    stack = declaration.read()
    entry = stack.hosts[stack.roles["sensor"]]

    assert entry.rules == "/var/lib/suricata/rules/local.rules"
    assert (ROOT / openstack.BASELINE_RULES).is_file(), (
        "a slot's configure seeds the sensor from local.rules; the ready check reads the sensor's rules against it")


