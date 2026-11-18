def test_submitting_the_exfiltrated_hashes_credits_the_full_ladder(board_session):
    submitted = board_session["real_loot"]

    assert submitted.status_code == 200, submitted.text
    assert set(submitted.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert submitted.json()["coverage"] == 1.0


def test_fabricated_loot_is_refused_against_the_live_snapshot(board_session):
    submitted = board_session["fabricated_loot"]

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["credited"] == []
