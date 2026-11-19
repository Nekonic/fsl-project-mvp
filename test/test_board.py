import plays

SILENCED_CASE = "board-path-traversal-static"


def test_an_attack_on_the_board_is_detected_and_a_benign_request_passes(full_run):
    lines = plays.per_case(full_run["score"])

    attacked = lines.get("board-sqli-search")
    assert attacked is not None and attacked["verdict"] == "tp", f"the board SQLi raised no alert: {lines}"
    assert attacked["corroborated"], (
        f"the alert did not mention the attack's own mechanism: {attacked}"
    )

    passed = lines.get("board-normal-search")
    assert passed is not None and passed["verdict"] == "tn", (
        f"an ordinary board search raised an alert: {passed}"
    )

    totals = plays.totals(full_run["score"])
    assert totals["tp"] > 0 and totals["tn"] > 0, totals


def test_each_engine_sees_the_board_sqli(full_run):
    seen = plays.engines(full_run["alerts"], full_run["markers"]["board-sqli-search"])

    assert seen == {"ids", "waf"}, f"only {sorted(seen)} saw the board SQLi"


def test_the_rule_catches_the_attack_before_anything_is_disabled(full_run):
    assert plays.per_case(full_run["score"])[SILENCED_CASE]["verdict"] == "tp", (
        "the attack was not detected even with its rule on, so test_disabled_rule "
        "cannot show what disabling the rule costs"
    )
