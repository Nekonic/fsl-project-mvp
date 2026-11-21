import pytest

import plays

CASE = "board-sqli-search"
O_BRIEN = "board-normal-search-with-apostrophe"
PROBE = 'alert http any any -> any any (msg:"round isolation probe"; sid:9009901; rev:1;)\n'


def o_brien(played: plays.Played) -> int:
    request = next(case for case in plays.declared_cases("board") if case["name"] == O_BRIEN)["request"]
    sent = plays.send(played, request["method"], request["path"], query=dict(request.get("params") or {}))
    assert sent.ok, sent.text
    return sent.body["status"]


@pytest.fixture(scope="module")
def two_allocations(stack_is_up):
    opened = [plays.play("board")]
    try:
        opened.append(plays.play("board"))
        first, second = opened
        marker = plays.fired(first, CASE)["marker"]
        plays.alerts_until(first, lambda listed: bool(plays.marked(listed, marker)))
        seen = {
            "first": first.round, "second": second.round, "marker": marker,
            "open": {row["round"] for row in plays.open_rounds()},
            "second_alerts": plays.alerts(second),
            "second_cases": set(plays.per_case(plays.score(second).body)),
        }

        assert plays.tune_waf(second, {"paranoia": 4}).ok
        assert plays.tune_waf(first, {"paranoia": 1}).ok
        committed = plays.declared_rules()
        seen["committed"] = committed
        seen["applied"] = plays.apply_ids(first, committed + PROBE)
        seen["second_tuning"] = plays.waf_posture(second)["posture"]
        seen["first_rules"] = plays.ids_rules(first)["text"]
        seen["second_rules"] = plays.ids_rules(second)["text"]
        seen["served"] = o_brien(first)
        seen["refused"] = o_brien(second)
    finally:
        for played in opened:
            plays.close(played)
    return seen


def test_both_rounds_stay_open_at_once(two_allocations):
    assert {two_allocations["first"], two_allocations["second"]} <= two_allocations["open"], (
        "opening the second allocation closed the first round or took its stack down"
    )


def test_an_attack_in_one_round_draws_no_alert_in_the_other(two_allocations):
    assert not plays.marked(two_allocations["second_alerts"], two_allocations["marker"]), (
        f"round {two_allocations['second']} took in alerts drawn by round {two_allocations['first']}'s attack: its "
        f"index or its sensor is shared"
    )
    assert CASE not in two_allocations["second_cases"], f"round {two_allocations['first']}'s case was scored in the other"


def test_two_rounds_tune_their_own_waf_and_their_own_sensor(two_allocations):
    seen = two_allocations

    assert seen["applied"].status == 200, seen["applied"].text
    assert seen["first_rules"] == seen["committed"] + PROBE
    assert seen["second_rules"] == seen["committed"], "a rule applied in one round reached another's sensor"
    assert seen["second_tuning"]["paranoia"] == 4, "a tuning applied in one round reached another's record"
    assert (seen["served"], seen["refused"]) == (200, 403), (
        "paranoia level 1 in the first round and 4 in the second should serve and "
        f"block the O'Brien search respectively; got {seen['served']} and {seen['refused']}"
    )
