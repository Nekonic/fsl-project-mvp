import plays


def test_a_board_round_starts_with_no_objective_lost(board_session):
    held = board_session["objectives_at_start"]

    assert {line["key"] for line in held} == set(plays.objective_keys("board")), held
    assert {line["state"] for line in held} == {"kept"}, held


def test_a_breach_is_scored_and_attributed_to_the_attack_that_took_it(board_session):
    submitted = board_session["real_loot"]
    assert submitted.status == 200, submitted.text
    assert submitted.body["lost"], "the exfiltrated hashes lost no objective"

    lost = board_session["scored"]["objectives"]["lost"]
    assert {breach["key"] for breach in lost} == set(plays.objective_keys("board")), lost
    assert board_session["control_alerts"], (
        "the attack that took the loot drew no alert, so a breach tied to it reads exactly like one tied to nothing"
    )
    assert lost, "nothing was taken, so attribution proves nothing"
    for breach in lost:
        assert (breach["attributed_marker"], breach["detected"]) == (board_session["marker"], True), (
            f"the loot was taken right after the SQLi case, so each breach must be tied to that case and detected "
            f"through its alerts; {breach['key']} carried {breach}"
        )


def test_attacks_the_defence_detected_take_no_objective_without_the_target_s_own_record(full_run):
    objectives = full_run["score"]["objectives"]

    assert plays.totals(full_run["score"])["tp"] > 0
    assert objectives["lost"] == [], (
        f"no loot was submitted and the board's data did not change, yet the score marked objectives lost: "
        f"{objectives['lost']}. Only the target decides an objective")
    assert {line["key"] for line in objectives["kept"]} == set(plays.objective_keys("board")), objectives["kept"]
    assert objectives["weighted"] == 0
