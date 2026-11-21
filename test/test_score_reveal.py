def test_a_player_reads_no_score_while_the_round_runs_and_reads_it_once_ended(board_session):
    while_running = board_session["score_while_running"]
    assert while_running.status == 409 and "round_running" in while_running.codes, (
        f"the score leaked to a player before the round ended; a live tally lets either side play to the number: "
        f"{while_running.text}"
    )

    assert board_session["ended"].ok, board_session["ended"].text

    after = board_session["score_once_ended"]
    assert after.status == 200, after.text
    assert set(after.body) >= {"objectives", "outcomes", "free_actions"}, after.body
    assert "tp" not in after.body["objectives"], "the objective number and the per-case outcomes are kept apart"
