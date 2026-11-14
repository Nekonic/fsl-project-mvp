SILENCED_CASE = "board-path-traversal-static"


def _case(score, name):
    return next((c for c in score["per_case"] if c["name"] == name), None)


def test_an_attack_on_the_board_is_detected_and_a_benign_request_passes(full_run):
    score = full_run["score"]

    attacked = _case(score, "board-sqli-search")
    assert attacked is not None and attacked["detected"], f"the board SQLi raised no alert: {score}"
    assert attacked["corroborated"], (
        f"the alert did not mention the attack's own mechanism: {attacked}"
    )

    passed = _case(score, "board-normal-search")
    assert passed is not None and not passed["detected"], (
        f"an ordinary board search raised an alert: {passed}"
    )

    assert score["tp"] > 0 and score["tn"] > 0, score


def test_the_rule_catches_the_attack_before_anything_is_disabled(full_run):
    before = full_run["score"]

    assert _case(before, SILENCED_CASE)["verdict"] == "TP", (
        "the attack was not detected even with its rule on, so test_disabled_rule "
        "cannot show what disabling the rule costs"
    )
