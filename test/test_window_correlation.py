import pytest

import plays
from shared_sessions import CONTROL, with_token


def test_a_free_tool_run_is_attributed_to_its_origin_by_time_and_source(terminal_windows):
    free = {row["ip"]: row for row in terminal_windows["score"]["free_actions"]["by_origin"]}
    origin = terminal_windows["origin"]["ip"]

    assert free.get(origin, {}).get("alerts", 0) > 0, (
        f"the free tool's alerts were tied to no action of {origin}: {terminal_windows['score']['free_actions']}"
    )


def test_the_free_tool_s_traffic_drew_alerts_from_the_origin_it_left_by(terminal_windows):
    drawn = with_token(terminal_windows["alerts"], terminal_windows["window_token"])

    assert drawn, "the free tool's probe drew no alert, so there was nothing to attribute"
    assert {alert["src_ip"] for alert in drawn} == {terminal_windows["origin"]["ip"]}


@pytest.mark.parametrize("strategy", ["marker", "window"])
def test_a_free_action_never_becomes_a_per_case_decision(terminal_windows, strategy):
    lines = {line["case"] for line in terminal_windows["by"][strategy]["outcomes"]["per_case"]}

    declared = {case["name"] for case in plays.declared_cases("board")}

    assert CONTROL in lines and lines <= declared, sorted(lines - declared)
