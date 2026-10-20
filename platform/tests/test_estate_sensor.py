import pathlib
from unittest.mock import patch

import pytest
import yaml

from range import declared
from tests.test_rules_port import RELOAD, RULE, Sensor

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXTRA = (("estate-sensor", "/var/lib/suricata/rules/local.rules", RELOAD),)

class Standing:
    def __init__(self, edge, estate):
        self.sensors = {"sensor": edge, "estate-sensor": estate}

    def __call__(self):
        return self

    def runner(self, role, segment_id=""):
        return self.sensors[role]

def test_the_wargame_host_runs_the_pinned_sensor_image():
    host = yaml.safe_load((ROOT / "deploy/wargame-host/sensor.yaml").read_text())["services"]["suricata"]

    assert host["image"] == (
        "jasonish/suricata@sha256:7ca2546f7f2735f621b981b6a5ec84fb962984636f7629a1a2fa6a324d4b6840"
    ), "the inside leg is judged by one Suricata build, which moves only when this pin does"
    assert host["network_mode"] == "host"
    assert host["volumes"][0].endswith(":/etc/suricata/suricata.yaml")

def test_the_host_sensor_starts_on_docker_s_config_and_the_shipped_baseline_rules():
    entry = declared.read().hosts["fsl-wargame-host"]
    setup = (ROOT / entry.setup).read_text()
    host = yaml.safe_load((ROOT / "deploy/wargame-host/sensor.yaml").read_text())["services"]["suricata"]

    assert "deploy/suricata/suricata.yaml" in entry.files
    assert "../suricata/suricata.yaml /opt/fsl/suricata.yaml" in setup
    assert "deploy/suricata/rules/local.rules" in entry.files
    assert "../suricata/rules/local.rules /opt/fsl/rules/local.rules" in setup
    assert "/opt/fsl/rules:/var/lib/suricata/rules" in host["volumes"], (
        "the ready check reads every sensor's rules against local.rules; a host "
        "sensor started with none kept the range out of READY"
    )
    assert entry.rules == "/var/lib/suricata/rules/local.rules"

@pytest.mark.django_db
def test_a_rule_change_reaches_every_declared_sensor(client, settings):
    settings.FSL_EXTRA_SENSORS = EXTRA
    edge, estate = Sensor(reload=settings.FSL_SENSOR_RELOAD), Sensor()

    with patch("api.views.substrate", Standing(edge, estate)):
        applied = client.post_json("/api/rules/apply/", {"content": RULE})

    assert applied.status_code == 200, applied.content
    assert edge.files[settings.FSL_SENSOR_RULES] == RULE
    assert estate.files["/var/lib/suricata/rules/local.rules"] == RULE, (
        "docker's one sensor judges both legs with one rule set; on openstack "
        "the inside leg's sensor must hold the same rules as the edge"
    )

@pytest.mark.django_db
def test_a_rule_change_one_sensor_refuses_is_taken_back_from_the_others(client, settings):
    settings.FSL_EXTRA_SENSORS = EXTRA
    edge, estate = Sensor(), Sensor(fails_on="-T")
    edge.files[settings.FSL_SENSOR_RULES] = "previous\n"

    with patch("api.views.substrate", Standing(edge, estate)):
        applied = client.post_json("/api/rules/apply/", {"content": RULE})

    assert applied.status_code != 200
    assert edge.files[settings.FSL_SENSOR_RULES] == "previous\n", (
        "two sensors holding different rules would score the two legs by different defences"
    )
