import time

import pytest

import plays
from shared_sessions import CATCH_ALL

BLOCK_EVERYTHING = plays.at_paranoia(4, inbound=1)
SETUP = plays.Setup(wargame="board", title="Acceptance block everything board",
                    suricata_rules=plays.declared_rules() + CATCH_ALL, waf_files=BLOCK_EVERYTHING)
FIRING_ROUNDS = 3
BENIGN_WAIT = 2 * plays.BENIGN_EVERY_S + 60.0


def http_attacks(played: plays.Played) -> list[str]:
    return [line["case"] for line in plays.cases_listed(played) if line["malicious"] and line["kind"] == "http"]


def fire_every_case(played: plays.Played) -> list[plays.Answer]:
    cases = http_attacks(played)
    return [plays.fire(played, case) for _ in range(FIRING_ROUNDS) for case in cases]


@pytest.fixture(scope="module")
def blocked_round():
    with plays.Round("board", SETUP) as played:
        answers = fire_every_case(played)
        time.sleep(BENIGN_WAIT)
        state = plays.attack_seen(played)
        plays.end(played)
        scored = plays.score(played)
        yield {"answers": answers, "state": state, "scored": scored,
               "benign": {case["name"] for case in plays.declared_cases("board") if case.get("malicious") is False}}


def test_crs_refusing_every_attack_spends_no_origin(blocked_round):
    refused = [answer for answer in blocked_round["answers"] if (answer.body or {}).get("status") == 403]

    assert refused, "the block-everything WAF files refused none of the attacks"
    assert blocked_round["state"]["remaining"]["spent"] == [], (
        "a CRS 403 spends nothing; only an nginx deny or limit_req in the WAF's error log does")


def test_a_block_everything_defence_shows_its_false_positives_beside_the_objectives(blocked_round):
    assert blocked_round["scored"].ok, blocked_round["scored"].text
    lines = plays.per_case(blocked_round["scored"].body)
    benign_fp = [case for case, line in lines.items() if case in blocked_round["benign"] and line["verdict"] == "fp"]

    assert plays.totals(blocked_round["scored"].body)["fp"] > 0 and benign_fp, (
        f"a defence that refuses everything showed no false positive on the benign set before the round ended: "
        f"{plays.totals(blocked_round['scored'].body)}")
