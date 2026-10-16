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
