import pytest
import requests

from conftest import PLATFORM_URL

@pytest.fixture(scope="module")
def marker_only_session(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    for name in ("sqli-login-bypass", "normal-product-search"):
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": name}, timeout=300,
        )
        assert sent.status_code == 201, sent.text

    from conftest import score_when_ready

    score_when_ready(session_id, lambda totals: totals["tp"] > 0)
    return session_id

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
    assert "sqli-login-bypass" in named[0][1], named

def test_the_console_is_given_the_reason_and_not_only_the_number():
    import pathlib

    console = (
        pathlib.Path(__file__).resolve().parents[1]
        / "platform/console/templates/console/blue.html"
    ).read_text()
    panel = console[console.index("async function renderComparison"):]
    panel = panel[:panel.index("\n  }")]

    assert "warnings" in panel, (
        "the comparison panel renders tp/fn/fp/tn for both strategies and "
        "throws the warnings away, so a zero that means 'this cannot be "
        "measured' is drawn identically to a zero that means 'nothing was "
        "detected'"
    )

def test_the_two_strategies_still_disagree_for_a_real_reason(marker_only_session):
    marker = scored(marker_only_session, "marker")
    window = scored(marker_only_session, "window")

    assert marker["tp"] > window["tp"], (
        f"marker {marker['tp']} vs window {window['tp']} - if these agree, "
        f"the case in this session is carrying a source address it should "
        f"not have, and the comparison is no longer comparing anything"
    )
