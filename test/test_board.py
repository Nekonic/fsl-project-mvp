import plays
from shared_rounds import CONTROL, UNION


def test_an_attack_on_the_board_is_detected_and_a_benign_request_passes(full_run):
    lines = plays.per_case(full_run["score"])

    attacked = lines.get(CONTROL)
    assert attacked is not None and attacked["verdict"] == "tp", f"the board SQLi raised no alert: {lines}"
    assert attacked["corroborated"], (
        f"the alert did not mention the attack's own mechanism: {attacked}"
    )

    passed = lines.get("board-normal-search")
    assert passed is not None and passed["verdict"] == "tn", (
        f"an ordinary board search raised an alert: {passed}"
    )


def test_each_engine_sees_the_board_sqli(full_run):
    seen = plays.engines(full_run["alerts"], full_run["markers"][CONTROL])

    assert seen == {"ids", "waf"}, f"only {sorted(seen)} saw the board SQLi"


def test_the_ids_sees_the_union_select_shape_not_only_the_control_one(full_run):
    seen = plays.engines(full_run["alerts"], full_run["markers"][UNION])

    assert plays.per_case(full_run["score"])[UNION]["verdict"] == "tp"
    assert "ids" in seen, (
        f"only {sorted(seen)} caught the union-select injection - the IDS rules match one SQLi shape rather than "
        f"the attack, and the WAF is covering for them"
    )
