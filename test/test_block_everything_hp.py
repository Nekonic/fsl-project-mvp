import pytest

import plays
from shared_sessions import CATCH_ALL

HP = {"budget": 60, "per_request": 1, "refused_x": 3, "burst_per_s": 1000, "burst_x": 1}
BLOCK_EVERYTHING = {"paranoia": 4, "exclusions": [], "thresholds": {"inbound": 1}}
SETUP = plays.Setup(wargame="board", title="Acceptance block everything under HP board", hp=HP,
                    suricata_rules=plays.declared_rules() + CATCH_ALL, crs_tuning=BLOCK_EVERYTHING)
MOST_FIRINGS = 400
END_WAIT = 4 * plays.BENIGN_EVERY_S + 120.0


def http_attacks(played: plays.Played) -> list[str]:
    return [line["case"] for line in plays.cases_listed(played) if line["malicious"] and line["kind"] == "http"]


def fire_until_spent(played: plays.Played) -> list[plays.Answer]:
    cases, answers = http_attacks(played), []
    for at in range(MOST_FIRINGS):
        answer = plays.fire(played, cases[at % len(cases)])
        answers.append(answer)
        if "origins_spent" in answer.codes or "round_closed" in answer.codes:
            break
    return answers


@pytest.fixture(scope="module")
def blocked_round():
    with plays.Round("board", SETUP) as played:
        answers = fire_until_spent(played)
        shown = plays.ended_round(played, END_WAIT)
        scored = plays.score(played)
        yield {"answers": answers, "shown": shown, "scored": scored,
               "benign": {case["name"] for case in plays.declared_cases("board") if case.get("malicious") is False}}


def test_the_attack_runs_out_of_origins_against_a_defence_that_refuses_everything(blocked_round):
    codes = [code for answer in blocked_round["answers"] for code in answer.codes]

    assert "origins_spent" in codes, f"the attack never ran out of origins in {len(blocked_round['answers'])} firings"


def test_origins_spent_ends_the_round_only_after_the_benign_set_has_run(blocked_round):
    assert blocked_round["shown"]["phase"] == "ended", blocked_round["shown"]
    assert blocked_round["shown"]["end_reason"] == "origins_spent", blocked_round["shown"]


def test_a_block_everything_defence_shows_its_false_positives_beside_the_objectives(blocked_round):
    assert blocked_round["scored"].ok, blocked_round["scored"].text
    lines = plays.per_case(blocked_round["scored"].body)
    benign_fp = [case for case, line in lines.items() if case in blocked_round["benign"] and line["verdict"] == "fp"]

    assert plays.totals(blocked_round["scored"].body)["fp"] > 0 and benign_fp, (
        f"a defence that refuses everything showed no false positive on the benign set before the round ended: "
        f"{plays.totals(blocked_round['scored'].body)}")
