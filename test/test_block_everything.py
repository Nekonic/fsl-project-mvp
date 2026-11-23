import pytest

import plays
from shared_sessions import CATCH_ALL

SETUP = plays.Setup(wargame="board", title="Acceptance block everything board",
                    suricata_rules=plays.declared_rules() + CATCH_ALL,
                    waf_files={plays.CRS_EXCLUSIONS: plays.paranoia(4, inbound=1)})
FIRING_ROUNDS = 3
BENIGN_WAIT = 2 * plays.BENIGN_EVERY_S + 60.0


def http_attacks(played: plays.Played) -> list[str]:
    return [line["case"] for line in plays.cases_listed(played) if line["malicious"] and line["kind"] == "http"]


def fire_every_case(played: plays.Played) -> list[plays.Answer]:
    cases = http_attacks(played)
    return [plays.fire(played, case) for _ in range(FIRING_ROUNDS) for case in cases]


def benign_fp(scored: dict, benign: set[str]) -> list[str]:
    return [case for case, line in plays.per_case(scored).items() if case in benign and line["verdict"] == "fp"]


@pytest.fixture(scope="module")
def blocked_round():
    benign = {case["name"] for case in plays.declared_cases("board") if case.get("malicious") is False}
    with plays.Round("board", SETUP) as played:
        answers = fire_every_case(played)
        plays.score_when_ready(played, until=lambda scored: bool(benign_fp(scored, benign)), timeout=BENIGN_WAIT)
        state = plays.attack_seen(played)
        spent = plays.events(played, {"origin.spent"})
        plays.end(played)
        scored = plays.score(played)
        yield {"answers": answers, "state": state, "spent": spent, "scored": scored, "benign": benign}


def test_crs_refusing_every_attack_spends_no_origin(blocked_round):
    refused = [answer for answer in blocked_round["answers"] if (answer.body or {}).get("status") == 403]
    state = blocked_round["state"]

    assert refused, "the block-everything WAF files refused none of the attacks"
    assert blocked_round["spent"] == [], (
        f"a CRS 403 spends nothing; only an nginx deny or limit_req in the WAF's error log does: {blocked_round['spent']}")
    assert state["remaining"]["spent"] == [] and state["remaining"]["left"] == len(state["origins"]), state["remaining"]
    assert all(origin["spent_at"] is None for origin in state["origins"]), state["origins"]


def test_a_block_everything_defence_shows_its_false_positives_beside_the_objectives(blocked_round):
    assert blocked_round["scored"].ok, blocked_round["scored"].text
    scored = blocked_round["scored"].body

    assert plays.totals(scored)["fp"] > 0 and benign_fp(scored, blocked_round["benign"]), (
        f"a defence that refuses everything showed no false positive on the benign set: {plays.totals(scored)}")
    assert scored["objectives"]["lost"] == [] and scored["objectives"]["weighted"] == 0, scored["objectives"]
