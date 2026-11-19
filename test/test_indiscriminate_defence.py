import pytest

import plays
from shared_sessions import CATCH_ALL_ATTACKS, CATCH_ALL_BENIGN


def indiscriminate(listed: list[dict], attack_markers: set[str]) -> set[str]:
    return {alert["signature"] for alert in listed if alert["request_id"] and alert["request_id"] not in attack_markers}


@pytest.fixture(scope="module")
def block_everything(rules_session):
    lines = plays.per_case(rules_session["after_catch_all"])
    phase = {name: lines[name] for name in CATCH_ALL_ATTACKS + CATCH_ALL_BENIGN if name in lines}
    return phase, rules_session["catch_all_markers"], rules_session["catch_all_alerts"]


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

    for name, marker in markers.items():
        if phase.get(name, {}).get("corroborated") is not True:
            continue
        own = {alert["signature"] for alert in plays.marked(listed, marker)}
        assert own - noise, (
            f"{name} was credited with a real detection, and every signature it drew also fired on traffic "
            f"meant to pass: {own}. The defence writes that text, so a block-everything rule set wins the one "
            f"number meant to stop it"
        )
