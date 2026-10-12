import pytest
import requests

from conftest import PLATFORM_URL

@pytest.fixture(scope="module")
def marker_only_session(full_run):
    return full_run["session_id"]

def scored(session_id, strategy):
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/score/?correlation={strategy}",
        timeout=120,
    ).json()

def test_a_strategy_that_cannot_place_a_case_says_which_ones(marker_only_session):
    window = scored(marker_only_session, "window")

    named = [w for w in window["warnings"] if w[0] == "score.warning.no_source_ip"]

    assert named, (
        "forcing time-window correlation onto cases that declare no source "
        "address gives every one of them a miss, and the score said nothing. "
        "An operator reads that as a defence that failed"
    )
    assert "board-sqli-search" in named[0][1], named

def test_the_two_strategies_still_disagree_for_a_real_reason(marker_only_session):
    marker = scored(marker_only_session, "marker")
    window = scored(marker_only_session, "window")

    assert marker["tp"] > window["tp"], (
        f"marker {marker['tp']} vs window {window['tp']} - if these agree, "
        f"the case in this session is carrying a source address it should "
        f"not have, and the comparison is no longer comparing anything"
    )
