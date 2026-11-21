import pytest

import plays
from bots.client import AuthenticatedClient

HP = {"budget": 30, "per_request": 1, "refused_x": 3, "burst_per_s": 1000, "burst_x": 1}
SETUP = plays.Setup(wargame="board", title="Acceptance bot rounds board", side="both",
                    matchups=("def_vs_bot", "atk_vs_bot"), hp=HP)
CONTROL = "board-sqli-search"
MOST_FIRINGS = 200
BOT_RULE = (
    'alert http any any -> any any (msg:"bot rule for SQL injection in search"; '
    'flow:established,to_server; http.uri; content:"or 1=1"; nocase; sid:9009983; rev:1;)\n'
)


def attack_bot_baseline(played: plays.Played) -> list[plays.Answer]:
    cases = [line["case"] for line in plays.cases_listed(played) if line["malicious"] and line["kind"] == "http"]
    answers, first = [], plays.attack_seen(played)["hp"]["origin"]["ip"]
    for at in range(MOST_FIRINGS):
        answer = plays.fire(played, cases[at % len(cases)])
        answers.append(answer)
        hp = (answer.body or {}).get("hp") or {}
        if "origins_spent" in answer.codes or (hp.get("origin") or {}).get("ip") not in (None, first):
            break
    return answers


def defence_bot_turn(played: plays.Played, marker: str) -> dict:
    listed = plays.alerts_until(played, lambda listed: bool(plays.marked(listed, marker)))
    text = plays.ids_rules(played)["text"] + BOT_RULE
    tested = plays.rule_test_ids(played, text)
    applied = plays.apply_ids(played, text, tested=tested.body.get("test") if tested.ok else None)
    return {"alerts": listed, "tested": tested, "applied": applied, "traffic": plays.traffic(played)}


def finished(played: plays.Played, bot) -> dict:
    plays.end(played)
    return {"shown": plays.round_shown(played, client=bot), "score": plays.score(played, client=bot),
            "events": plays.events(played)}


@pytest.fixture(scope="module")
def attack_bot_round():
    with plays.Round("board", SETUP, matchup="def_vs_bot") as played:
        assert isinstance(played.attack, AuthenticatedClient)
        answers = attack_bot_baseline(played)
        yield {"answers": answers, **finished(played, played.attack)}


@pytest.fixture(scope="module")
def defence_bot_round():
    with plays.Round("board", SETUP, matchup="atk_vs_bot") as played:
        assert isinstance(played.defence, AuthenticatedClient)
        marker = plays.fired(played, CONTROL)["marker"]
        turn = defence_bot_turn(played, marker)
        yield {"marker": marker, **turn, **finished(played, played.defence)}


def test_the_attack_bot_reads_hp_on_every_answer_and_moves_origin_when_one_is_spent(attack_bot_round):
    assert all("hp" in (answer.body or {}) for answer in attack_bot_round["answers"])
    kinds = {event["kind"] for event in attack_bot_round["events"]}
    assert {"origin.spent", "origin.switched"} <= kinds, kinds


@pytest.mark.parametrize("bot_round", ["attack_bot_round", "defence_bot_round"])
def test_a_bot_player_reads_the_end_and_the_score_with_its_own_token(bot_round, request):
    played = request.getfixturevalue(bot_round)

    assert played["shown"].ok and played["shown"].body["phase"] == "ended", played["shown"].text
    assert played["score"].ok, played["score"].text
    assert {"objectives", "outcomes", "free_actions"} <= set(played["score"].body)
    assert played["score"].body["outcomes"]["note"] == "one_case_one_decision"


def test_the_defence_bot_sees_the_attack_and_applies_a_tested_rule(defence_bot_round):
    assert plays.marked(defence_bot_round["alerts"], defence_bot_round["marker"]), (
        "the defence bot's alerts never showed the human attacker's case")
    assert defence_bot_round["tested"].ok, defence_bot_round["tested"].text
    assert defence_bot_round["applied"].ok, defence_bot_round["applied"].text
    assert defence_bot_round["applied"].body["same_as_tested"] is True
    assert defence_bot_round["traffic"]["by_origin"], "the defence bot's traffic view was empty"
