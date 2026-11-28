import pytest

import plays

CASE = "board-sqli-search"
PROBE_PATH = "/round-isolation-probe/"
PROBE = ('alert http any any -> any any (msg:"round isolation probe"; flow:established,to_server; '
         f'http.uri; content:"{PROBE_PATH}"; sid:9009901; rev:1;)\n')


def probed(played: plays.Played) -> int:
    sent = plays.send(played, "GET", PROBE_PATH)
    assert sent.ok, sent.text
    return sent.body["status"]


def with_waf_probe(played: plays.Played) -> dict[str, str]:
    return plays.appended(played, plays.CRS_EXCLUSIONS, plays.refusing_path(PROBE_PATH, 10077))


@pytest.fixture(scope="module")
def two_allocations(stack_is_up):
    opened = [plays.play("board")]
    try:
        opened.append(plays.play("board"))
        first, second = opened
        marker = plays.fired(first, CASE)["marker"]
        plays.alerts_until(first, lambda listed: bool(plays.marked(listed, marker)))
        own = plays.fired(second, CASE)["marker"]
        seen = {
            "first": first.round, "second": second.round, "marker": marker, "own": own,
            "open": {row["round"] for row in plays.open_rounds()},
            "second_alerts": plays.alerts_until(second, lambda listed: bool(plays.marked(listed, own))),
        }
        seen["second_lines"] = [line["case"] for line in plays.score(second).body["outcomes"]["per_case"]]

        tuned = plays.tune_waf(second, with_waf_probe(second))
        assert tuned.ok, tuned.text
        committed = plays.declared_rules(first.wargame)
        seen["committed"] = committed
        seen["applied"] = plays.apply_ids(first, committed + PROBE)
        seen["first_tuning"] = plays.waf_files(first)[plays.CRS_EXCLUSIONS]
        seen["second_tuning"] = plays.waf_files(second)[plays.CRS_EXCLUSIONS]
        seen["first_rules"] = plays.ids_rules(first)["text"]
        seen["second_rules"] = plays.ids_rules(second)["text"]
        seen["served"] = probed(first)
        seen["refused"] = probed(second)
    finally:
        for played in opened:
            plays.close(played)
    return seen


def test_both_rounds_stay_open_at_once(two_allocations):
    assert {two_allocations["first"], two_allocations["second"]} <= two_allocations["open"], (
        "opening the second allocation closed the first round or took its stack down"
    )


def test_an_attack_in_one_round_draws_no_alert_in_the_other(two_allocations):
    assert plays.marked(two_allocations["second_alerts"], two_allocations["own"]), (
        f"round {two_allocations['second']} took in no alert for its own attack, so its ingest proves nothing")
    assert not plays.marked(two_allocations["second_alerts"], two_allocations["marker"]), (
        f"round {two_allocations['second']} took in alerts drawn by round {two_allocations['first']}'s attack: its "
        f"index or its sensor is shared"
    )
    assert two_allocations["second_lines"].count(CASE) == 1, (
        f"round {two_allocations['first']}'s case was scored in the other: {two_allocations['second_lines']}")


def test_two_rounds_tune_their_own_waf_and_their_own_sensor(two_allocations):
    seen = two_allocations

    assert seen["applied"].ok, seen["applied"].text
    assert seen["first_rules"] == seen["committed"] + PROBE
    assert seen["second_rules"] == seen["committed"], "a rule applied in one round reached another's sensor"
    assert "id:10077" in seen["second_tuning"] and "id:10077" not in seen["first_tuning"], (
        "a WAF rule applied in one round reached another's")
    assert seen["served"] != 403 and seen["refused"] == 403, (
        f"the rule applied only in the second round should refuse {PROBE_PATH} there and nowhere else; "
        f"got {seen['served']} in the first and {seen['refused']} in the second"
    )
