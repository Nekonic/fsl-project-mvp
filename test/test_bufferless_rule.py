import pytest


@pytest.fixture(scope="module")
def caught_by_a_rule_without_a_buffer(rules_session):
    return rules_session["bufferless"]


def test_a_rule_without_an_app_layer_buffer_still_credits_the_case_it_caught(caught_by_a_rule_without_a_buffer):
    totals, case_id, sigs = caught_by_a_rule_without_a_buffer
    owned = next(c for c in totals["per_case"] if c["case_id"] == case_id)
    fired = [d for d, s in sigs.items() if s.startswith("FSL UNION without a buffer")]

    assert fired, "the buffer-less rule never fired, so this proves nothing about the join"
    assert set(fired) & set(owned["detection_ids"]), (
        f"the rule fired {len(fired)} times on the case's own request, but an alert "
        f"from a signature with no app-layer keyword carries no tx_id, so it met no "
        f"http event, got no marker, and the case it caught did not own it"
    )
