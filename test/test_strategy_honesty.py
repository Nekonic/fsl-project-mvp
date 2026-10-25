import pytest


@pytest.fixture(scope="module")
def scored_by(full_run):
    return full_run["scored_by"]

def test_a_strategy_that_cannot_place_a_case_says_which_ones(scored_by):
    window = scored_by["window"]

    named = [w for w in window["warnings"] if w[0] == "score.warning.no_source_ip"]

    assert named, (
        "forcing time-window correlation onto cases that declare no source "
        "address gives every one of them a miss, and the score said nothing. "
        "An operator reads that as a defence that failed"
    )
    assert "board-sqli-search" in named[0][1], named

def test_the_two_strategies_still_disagree_for_a_real_reason(scored_by):
    marker = scored_by["marker"]
    window = scored_by["window"]

    assert marker["tp"] > window["tp"], (
        f"marker {marker['tp']} vs window {window['tp']} - if these agree, "
        f"the case in this session is carrying a source address it should "
        f"not have, and the comparison is no longer comparing anything"
    )
