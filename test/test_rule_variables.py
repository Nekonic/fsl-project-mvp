import pytest

import plays
from shared_rounds import CONTROL, PORTED_MESSAGE, UNION


@pytest.fixture(scope="module")
def fired_with_a_ported_rule(rules_round):
    return rules_round["noisy_alerts"], rules_round["noisy_markers"]


def test_a_rule_written_against_http_ports_actually_fires(fired_with_a_ported_rule):
    listed, markers = fired_with_a_ported_rule
    ported = {name: [alert for alert in plays.marked(listed, markers[name]) if alert["signature"] == PORTED_MESSAGE]
              for name in (CONTROL, UNION)}

    assert any(ported.values()), (
        "a rule identical to the shipped one except that it says $HTTP_PORTS "
        "instead of any never fired on the case it was written for. Every published HTTP signature is written "
        "that way, so a defender pasting one gets a validated rule, a reloaded "
        "sensor, a case scored FN, and no way to tell a wrong regex from a "
        "wrong port variable"
    )
