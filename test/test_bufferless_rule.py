import pytest

import plays


@pytest.fixture(scope="module")
def caught_by_a_rule_without_a_buffer(rules_round):
    return rules_round["bufferless"]


def test_a_rule_without_an_app_layer_buffer_still_credits_the_case_it_caught(caught_by_a_rule_without_a_buffer):
    scored, marker, listed = caught_by_a_rule_without_a_buffer
    fired = [alert for alert in listed if alert["signature"].startswith("UNION without a buffer")]

    assert fired, "the buffer-less rule never fired, so this proves nothing about the join"
    assert plays.marked(fired, marker), (
        f"the rule fired {len(fired)} times on the case's own request, but an alert "
        f"from a signature with no app-layer keyword carries no tx_id, so it met no "
        f"http event, got no marker, and the case it caught did not own it"
    )
    assert plays.per_case(scored)["board-sqli-union-search"]["verdict"] == "tp"
