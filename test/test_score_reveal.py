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


@pytest.mark.parametrize("session, wargame, detected_in_round, responded_in_round", [
    ("board_session", "board", True, True), ("rogue_admin_session", "corp", False, False)])
def test_an_unanswered_loss_counts_double_an_answered_one_whatever_detection_says(session, wargame,
                                                                                   detected_in_round,
                                                                                   responded_in_round, request):
    seen = request.getfixturevalue(session)
    if "response" in seen:
        assert seen["response"].ok, f"the tested WAF rule refusing the attack did not go live: {seen['response'].text}"
    objectives = (seen["scored"] if "scored" in seen else seen["score"])["objectives"]
    difficulty = plays.objective_difficulties(wargame)
    expected = sum(difficulty[breach["key"]] * (0.5 if breach["responded"] else 1) for breach in objectives["lost"])

    assert objectives["lost"], f"no objective was lost in {session}, so the weighting proves nothing"
    assert any(breach["responded"] is responded_in_round for breach in objectives["lost"]), (
        f"{session} lost no objective with responded {responded_in_round}, so that weight goes unchecked: "
        f"{objectives['lost']}")
    assert objectives["weighted"] == expected, (
        f"lost objectives weigh their difficulty, halved when the defence responded before they fell, and kept "
        f"ones nothing: {objectives}")


@pytest.mark.parametrize("session, detected_in_round", [("board_session", True), ("rogue_admin_session", False)])
def test_a_lost_objective_carries_its_detection_mark_beside_the_weight(session, detected_in_round, request):
    seen = request.getfixturevalue(session)
    lost = (seen["scored"] if "scored" in seen else seen["score"])["objectives"]["lost"]

    assert any(breach["detected"] is detected_in_round for breach in lost), (
        f"{session} lost no objective with detected {detected_in_round}, so that mark goes unchecked: {lost}")
