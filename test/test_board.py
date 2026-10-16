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


def test_a_board_session_starts_with_no_objective_taken(board_session):
    observed = board_session["objectives_at_open"]
    assert observed.status_code == 200, observed.text
    assert observed.json() == {"achieved": 0, "total": 0}, observed.json()
