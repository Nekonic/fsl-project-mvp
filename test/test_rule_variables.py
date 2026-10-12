import pytest

@pytest.fixture(scope="module")
def fired_with_a_ported_rule(rules_session):
    return rules_session["listed"]

def test_a_rule_written_against_http_ports_actually_fires(fired_with_a_ported_rule):
    ported = [
        d for d in fired_with_a_ported_rule
        if d["signature"] == "FSL ported SQLi probe"
    ]

    assert ported, (
        "a rule identical to the shipped one except that it says $HTTP_PORTS "
        "instead of any never fired. Every published HTTP signature is written "
        "that way, so a defender pasting one gets a validated rule, a reloaded "
        "sensor, a case scored FN, and no way to tell a wrong regex from a "
        "wrong port variable"
    )

def test_the_variable_names_the_ports_the_sensor_can_see(stack_is_up):
    import pathlib

    import yaml

    sensor = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1]
         / "deploy/suricata/suricata.yaml").read_text()
    )
    declared = sensor["vars"]["port-groups"]["HTTP_PORTS"]

    assert "8080" not in str(declared), (
        f"HTTP_PORTS is {declared!r}. 8080 is the host-published port; it is "
        f"translated before the packet reaches any interface the sensor taps. "
        f"Measured over the last six hours: every alert is on 80 or 3000"
    )
