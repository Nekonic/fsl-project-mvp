import plays


def test_submitting_the_exfiltrated_hashes_loses_the_full_ladder(board_session):
    submitted = board_session["real_loot"]

    assert submitted.status == 200, submitted.text
    assert submitted.body["lost"] is True, submitted.body
    lost = {line["key"] for line in board_session["scored"]["objectives"]["lost"]}
    assert lost == set(plays.objective_keys("board")) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }


def test_fabricated_loot_is_refused_against_the_round_start_snapshot(board_session):
    submitted = board_session["fabricated_loot"]

    assert submitted.status == 200, submitted.text
    assert submitted.body["lost"] is False, submitted.body


def test_a_loot_answer_never_carries_the_secret(board_session):
    shown = board_session["real_loot"].text

    assert "hash" not in shown and "password" not in shown, shown
