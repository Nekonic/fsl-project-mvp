import pathlib
from unittest.mock import patch

import pytest
import yaml

from range import declared
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

def sensors():
    return yaml.safe_load((ROOT / "deploy/range-host/slot.yaml").read_text())["services"]


def test_the_one_sensor_runs_the_pinned_image_on_both_legs_of_the_waf():
    sensor = sensors()["sensor"]

    assert sensor["image"] == (
        "jasonish/suricata@sha256:7ca2546f7f2735f621b981b6a5ec84fb962984636f7629a1a2fa6a324d4b6840"
    ), "both legs are judged by one Suricata build, which moves only when this pin does"
    assert sensor["networks"]["estate"] == {"interface_name": "dmz"} and sensor["networks"]["web"] == {
        "interface_name": "web"}
    assert sensor["networks"]["mgmt"]["interface_name"] == "mgmt"
    assert sensor["volumes"][0].endswith(":/etc/suricata/suricata.yaml")


def test_the_sensor_starts_on_the_shipped_baseline_rules():
    stack = declared.read()
    entry = stack.hosts[stack.roles["sensor"]]
    volumes = sensors()["sensor"]["volumes"]

    assert "/opt/cr/s@slot@/sensor-rules:/var/lib/suricata/rules" in volumes, (
        "the ready check reads the sensor's rules against local.rules; a sensor started "
        "with none kept the range out of READY"
    )
    assert entry.rules == "/var/lib/suricata/rules/local.rules"
    assert "install -m 0644" in (ROOT / "deploy/range-host/slot.sh").read_text()


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
