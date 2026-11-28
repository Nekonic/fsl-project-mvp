import pytest

import plays
from shared_rounds import CATCH_ALL_ATTACKS, CATCH_ALL_BENIGN, CATCH_ALL_MESSAGE


def indiscriminate(listed: list[dict], attack_markers: set[str]) -> set[str]:
    return {alert["signature"] for alert in listed if alert["request_id"] and alert["request_id"] not in attack_markers}


@pytest.fixture(scope="module")
def block_everything(rules_round):
    lines = plays.per_case(rules_round["after_catch_all"])
    phase = {name: lines[name] for name in CATCH_ALL_ATTACKS + CATCH_ALL_BENIGN if name in lines}
    return phase, rules_round["catch_all_markers"], rules_round["catch_all_alerts"]


def test_the_experiment_is_valid_at_all(block_everything):
    phase, markers, listed = block_everything
    verdicts = [line["verdict"] for line in phase.values()]

    assert set(CATCH_ALL_ATTACKS) <= set(phase), phase
    assert "fp" in verdicts and "tp" in verdicts, (
        f"the catch-all rule did not fire on both attacks and benign traffic, so nothing below proves anything: "
        f"{verdicts}"
    )
    assert indiscriminate(listed, set(markers.values())), (
        "no signature fired on traffic meant to pass, so there is no indiscriminate defence here"
    )


def test_nothing_is_credited_to_a_signature_that_also_fires_on_benign_traffic(block_everything):
    phase, markers, listed = block_everything
    noise = indiscriminate(listed, set(markers.values()))
    checked = []

    assert CATCH_ALL_MESSAGE in noise, noise
    for name, marker in markers.items():
        own = {alert["signature"] for alert in plays.marked(listed, marker)}
        assert own == {CATCH_ALL_MESSAGE}, (
            f"{name} drew {own}; with the WAF's rule engine off the catch-all must be its only signature")
        assert phase[name]["verdict"] == "tp" and phase[name]["corroborated"] is False, (
            f"{name} was credited with a real detection, and every signature it drew also fired on traffic "
            f"meant to pass: {phase[name]}. The defence writes that text, so a block-everything rule set wins the "
            f"one number meant to stop it"
        )
        checked.append(name)
    assert sorted(checked) == sorted(CATCH_ALL_ATTACKS), checked
