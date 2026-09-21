import pathlib

import pytest

from range.ports import Ran, RangeUnavailable
from rules import suricata

RULE = 'alert http any any -> any any (msg:"x"; sid:9000900; rev:1;)\n'

class Sensor:
    def __init__(self, *, fails_on="", unreachable_on=""):
        self.calls = []
        self.files = {}
        self.fails_on = fails_on
        self.unreachable_on = unreachable_on

    def __call__(self, argv, stdin=None, timeout=60.0):
        self.calls.append((argv, stdin))
        joined = " ".join(argv)
        if self.unreachable_on and self.unreachable_on in joined:
            raise RangeUnavailable("the sensor is not there")
        if argv[0] == "sh" and stdin is not None:
            self.files[argv[-1].split(">")[-1].strip()] = stdin
            return Ran(0, "")
        if argv[0] == "cat":
            return Ran(0, self.files.get(argv[1], ""))
        if self.fails_on and self.fails_on in joined:
            return Ran(1, "bad rule")
        return Ran(0, "")

def test_core_never_names_the_substrate():
    source = pathlib.Path(suricata.__file__).read_text()

    assert "docker" not in source.lower(), (
        "platform/rules/ is gated core and would have to be rewritten for any "
        "substrate that is not Docker"
    )
    assert "range" not in source.split("\n")[0], "core must not import the port"

def test_a_rule_set_that_suricata_accepts_validates():
    outcome = suricata.validate(RULE, Sensor())

    assert outcome.ok

def test_a_rule_set_suricata_rejects_reports_what_it_said():
    outcome = suricata.validate(RULE, Sensor(fails_on="-T"))

    assert not outcome.ok
    assert "bad rule" in outcome.output

def test_applying_a_bad_rule_set_does_not_touch_the_live_rules():
    sensor = Sensor(fails_on="-T")

    with pytest.raises(suricata.RuleApplyError):
        suricata.apply(RULE, sensor)

    assert not any("USR2" in " ".join(argv) for argv, _ in sensor.calls), (
        "the sensor was told to reload a rule set it had just rejected"
    )

def test_a_reload_that_fails_rolls_the_rules_back():
    sensor = Sensor(fails_on="USR2")
    suricata.apply(RULE, Sensor())

    with pytest.raises(suricata.RuleApplyError, match="rolled back"):
        suricata.apply(RULE.replace("9000900", "9000901"), sensor)

def test_a_sensor_that_cannot_be_reached_is_not_a_bad_rule_set():
    with pytest.raises(RangeUnavailable):
        suricata.validate(RULE, Sensor(unreachable_on="-T"))

def test_the_rules_come_back_the_way_they_went_in():
    sensor = Sensor()
    suricata.apply(RULE, sensor)

    assert suricata.current(sensor) == RULE
