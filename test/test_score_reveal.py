def test_the_score_is_withheld_while_the_session_is_open_and_shown_once_closed(board_session):
    while_open = board_session["score_while_open"]
    assert while_open.status_code == 200, while_open.text
    assert while_open.json()["game"] == {"revealed": False}, (
        "the game score leaked before the session closed; a live tally lets "
        "either side play to the number"
    )

    closed = board_session["closed"]
    assert closed.status_code == 200, closed.text

    after = board_session["score_once_closed"]
    assert after["game"]["revealed"] is True, after["game"]
    for pillar in ("speed", "accuracy", "coverage", "balance"):
        assert pillar in after["game"], after["game"]
