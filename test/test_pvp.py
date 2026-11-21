import pytest

import plays

SETUP = plays.Setup(wargame="board", title="Acceptance pvp board", side="both", matchups=("pvp",))
CONTROL = "board-sqli-search"


@pytest.fixture(scope="module")
def pvp_round(stack_is_up):
    username, defender = plays.human_account()
    try:
        with plays.Round("board", SETUP, matchup="pvp", humans={"defence": (username, defender)}) as played:
            seen = {
                "attack_reads_defence": plays.ask("defence_state", played.attack, round_id=played.round),
                "defence_reads_attack": plays.ask("attack_state", played.defence, round_id=played.round),
                "defence_fires": plays.ask("attack_fire_case", played.defence, {"case": CONTROL},
                                           round_id=played.round),
                "attack_reads_alerts": plays.ask("defence_alerts", played.attack, round_id=played.round),
                "own_sides": (plays.ask("attack_state", played.attack, round_id=played.round),
                              plays.ask("defence_state", played.defence, round_id=played.round)),
            }
            plays.fired(played, CONTROL)
            plays.end(played)
            seen["scores"] = (plays.score(played, client=played.attack), plays.score(played, client=played.defence))
        yield seen
    finally:
        plays.account_disabled(username)


def test_each_human_player_is_refused_the_other_side_s_routes(pvp_round):
    for name in ("attack_reads_defence", "defence_reads_attack", "defence_fires", "attack_reads_alerts"):
        answer = pvp_round[name]
        assert answer.status == 403 and "not_a_player" in answer.codes, f"{name}: {answer.status} {answer.text}"
    assert all(answer.ok for answer in pvp_round["own_sides"]), [answer.text for answer in pvp_round["own_sides"]]


def test_both_human_players_read_the_same_score_once_the_round_ends(pvp_round):
    attack, defence = pvp_round["scores"]

    assert attack.ok and defence.ok, (attack.text, defence.text)
    assert attack.body == defence.body, "the two players of one ended round read different scores"
