import pytest

import plays


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


@pytest.mark.parametrize("session, wargame, seen_in_round", [
    ("board_session", "board", True), ("rogue_admin_session", "corp", False)])
def test_an_undetected_loss_counts_double_a_detected_one(session, wargame, seen_in_round, request):
    seen = request.getfixturevalue(session)
    objectives = (seen["scored"] if "scored" in seen else seen["score"])["objectives"]
    difficulty = plays.objective_difficulties(wargame)
    expected = sum(difficulty[breach["key"]] * (0.5 if breach["seen"] else 1) for breach in objectives["lost"])

    assert objectives["lost"], f"no objective was lost in {session}, so the weighting proves nothing"
    assert any(breach["seen"] is seen_in_round for breach in objectives["lost"]), (
        f"{session} lost no objective with seen {seen_in_round}, so that branch of the weighting goes unchecked: "
        f"{objectives['lost']}")
    assert objectives["weighted"] == expected, (
        f"lost objectives weigh their difficulty, halved when the defence saw them go, and kept ones nothing: "
        f"{objectives}")
