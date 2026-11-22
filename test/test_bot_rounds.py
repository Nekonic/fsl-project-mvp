import time

import pytest

import plays
from bots.signin import Platform

SETUP = plays.Setup(wargame="board", title="Acceptance bot rounds board", side="both",
                    matchups=("def_vs_bot", "atk_vs_bot"))
CONTROL = "board-sqli-search"


def attack_bot_baseline(played: plays.Played) -> list[plays.Answer]:
    cases = [line["case"] for line in plays.cases_listed(played) if line["malicious"] and line["kind"] == "http"]
    return [plays.fire(played, case) for case in cases]


def terminal_version(played: plays.Played) -> dict | None:
    deadline = time.monotonic() + plays.SCORE_WAIT
    while True:
        head = max(plays.waf_versions(played), key=lambda line: line["version"], default=None)
        if (head and head["source"] == "terminal") or time.monotonic() >= deadline:
            return head
        time.sleep(plays.POLL)


def bot_rule_alerts(played: plays.Played, marker: str) -> list[dict]:
    listed = plays.alerts_until(played, lambda listed: any(
        alert["signature"].startswith("bot rule") for alert in plays.marked(listed, marker)))
    return plays.marked(listed, marker)


def defence_bot_turn(played: plays.Played, marker: str) -> dict:
    listed = plays.alerts_until(played, lambda listed: bool(plays.marked(listed, marker)))
    shell = plays.tested_and_appended(played, plays.CRS_EXCLUSIONS, plays.BOT_SEARCH_RULE)
    head = terminal_version(played)
    live = plays.waf_files(played)[plays.CRS_EXCLUSIONS]
    fresh = plays.fired(played, CONTROL)["marker"]
    return {"alerts": listed, "shell": shell, "head": head, "live": live, "fresh": fresh,
            "fresh_alerts": bot_rule_alerts(played, fresh), "traffic": plays.traffic(played)}


def finished(played: plays.Played, bot) -> dict:
    running = plays.score(played, client=bot)
    plays.end(played)
    return {"running": running, "shown": plays.round_shown(played, client=bot),
            "score": plays.score(played, client=bot), "operator_score": plays.score(played)}


@pytest.fixture(scope="module")
def attack_bot_round():
    with plays.Round("board", SETUP, matchup="def_vs_bot") as played:
        assert isinstance(played.attack, Platform) and "Authorization" in played.attack.headers
        answers = attack_bot_baseline(played)
        yield {"answers": answers, **finished(played, played.attack)}


@pytest.fixture(scope="module")
def defence_bot_round():
    with plays.Round("board", SETUP, matchup="atk_vs_bot") as played:
        assert isinstance(played.defence, Platform) and "Authorization" in played.defence.headers
        marker = plays.fired(played, CONTROL)["marker"]
        turn = defence_bot_turn(played, marker)
        yield {"marker": marker, **turn, **finished(played, played.defence)}


@pytest.mark.parametrize("bot_round", ["attack_bot_round", "defence_bot_round"])
def test_a_bot_player_reads_the_end_and_the_score_with_its_own_token(bot_round, request):
    played = request.getfixturevalue(bot_round)

    assert played["running"].status == 409 and "round_running" in played["running"].codes, played["running"].text
    assert played["shown"].ok and played["shown"].body["phase"] == "ended", played["shown"].text
    assert played["score"].ok, played["score"].text
    assert played["score"].body == played["operator_score"].body, (
        "the bot read a different score from the operator's for the same ended round")


def test_the_defence_bot_sees_the_attack_and_changes_the_waf_through_its_shell(defence_bot_round):
    seen = defence_bot_round

    assert plays.marked(seen["alerts"], seen["marker"]), "the defence bot's alerts never showed the human attacker's case"
    assert seen["shell"]["ok"], seen["shell"]
    assert plays.BOT_SEARCH_RULE in seen["live"], "the bot's shell edit is not in the live WAF files"
    assert seen["head"] and seen["head"]["source"] == "terminal", (
        f"the bot's reload in its shell was not recorded as a terminal version: {seen['head']}")
    assert seen["fresh_alerts"] and any(alert["signature"].startswith("bot rule") for alert in seen["fresh_alerts"]), (
        f"a fresh {CONTROL} drew no alert from the bot's rule: {seen['fresh_alerts']}")
    assert seen["traffic"]["by_origin"], "the defence bot's traffic view was empty"
