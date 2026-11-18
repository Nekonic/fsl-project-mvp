import pathlib
from unittest.mock import patch

import pytest
from range import declared, openstack, sandbox
from tests.test_rules_port import RELOAD, RULE, Sensor

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


@pytest.mark.django_db
def test_a_rule_change_reaches_every_declared_sensor(client, settings):
    settings.CR_EXTRA_SENSORS = EXTRA
    edge, estate = Sensor(reload=settings.CR_SENSOR_RELOAD), Sensor()

    with patch("api.views.substrate", Standing(edge, estate)):
        applied = client.post_json("/api/rules/apply/", {"content": RULE})

    assert applied.status_code == 200, applied.content
    assert edge.files[settings.CR_SENSOR_RULES] == RULE
    assert estate.files["/var/lib/suricata/rules/local.rules"] == RULE, (
        "docker's one sensor judges both legs with one rule set; on openstack "
        "the inside leg's sensor must hold the same rules as the edge"
    )

@pytest.mark.django_db
def test_a_rule_change_one_sensor_refuses_is_taken_back_from_the_others(client, settings):
    settings.CR_EXTRA_SENSORS = EXTRA
    edge, estate = Sensor(), Sensor(fails_on="-T")
    edge.files[settings.CR_SENSOR_RULES] = "previous\n"

    with patch("api.views.substrate", Standing(edge, estate)):
        applied = client.post_json("/api/rules/apply/", {"content": RULE})

    assert applied.status_code != 200
    assert edge.files[settings.CR_SENSOR_RULES] == "previous\n", (
        "two sensors holding different rules would score the two legs by different defences"
    )
