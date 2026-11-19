import pytest

import plays

CONTROL = "board-sqli-search"
SECOND_SHAPE = "board-sqli-union-search"


@pytest.fixture(scope="module")
def fired(tuned_session):
    return tuned_session


def engines(fired, name):
    return plays.engines(fired["alerts"], fired["markers"][name])


def test_both_encodings_are_detected_and_each_engine_sees_the_attack_not_one_shape(fired):
    lines = plays.per_case(fired["score"])

    assert lines[CONTROL]["verdict"] == "tp"
    assert lines[SECOND_SHAPE]["verdict"] == "tp"
    assert {"ids", "waf"} <= engines(fired, CONTROL)
    assert "ids" in engines(fired, SECOND_SHAPE), (
        f"only {sorted(engines(fired, SECOND_SHAPE))} caught the union-select "
        f"injection - the IDS rules match one SQLi shape rather than the attack, "
        f"and the WAF is covering for them"
    )
