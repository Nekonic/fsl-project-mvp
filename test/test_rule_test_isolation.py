import json

import pytest

import plays

PROBED = "board-sqli-search"
CANDIDATE = (
    'alert http any any -> any any (msg:"candidate SQL injection in search"; '
    'flow:established,to_server; http.uri; content:"or 1=1"; nocase; sid:9009981; rev:1;)\n'
)
MANIFEST = plays.WARGAMES / "board" / "probes" / "manifest.json"
SETUP = plays.Setup(wargame="board", title="Acceptance rule test isolation board", probe_cases=(PROBED,))


def probe_markers() -> set[str]:
    if not MANIFEST.is_file():
        return set()
    cases = json.loads(MANIFEST.read_text()).get("cases") or {}
    return {str(entry.get("marker") or case) if isinstance(entry, dict) else case
            for case, entry in cases.items() if entry is not None}


def ground_truth(played: plays.Played) -> list[tuple[str, str]]:
    return sorted((line["key"], line["state"]) for line in plays.defence_seen(played)["objectives"])


@pytest.fixture(scope="module")
def tested_round():
    with plays.Round("board", SETUP) as played:
        before_truth, before_alerts = ground_truth(played), plays.alerts(played)
        ids = plays.rule_test_ids(played, plays.declared_rules() + CANDIDATE)
        edited = {**plays.appended(played, plays.CRS_SETUP, plays.paranoia(2)),
                  **plays.appended(played, plays.CRS_EXCLUSIONS, plays.STATIC_EXCLUDED)}
        waf = plays.rule_test_waf(played, edited)
        live = plays.fired(played, PROBED)["marker"]
        after_alerts = plays.alerts_until(played, lambda listed: bool(plays.marked(listed, live)))
        yield {"ids": ids, "waf": waf, "before_truth": before_truth, "after_truth": ground_truth(played),
               "before_alerts": before_alerts, "after_alerts": after_alerts, "live": live,
               "probes": plays.probes_listed(played)}


def test_both_rule_tests_answer_a_table(tested_round):
    assert {probe["case"]: probe["recorded"] for probe in tested_round["probes"]}.get(PROBED) is True, (
        f"{PROBED} has no recorded probe; run bin/record-probes board and commit the manifest")
    for engine in ("ids", "waf"):
        answer = tested_round[engine]
        assert answer.ok, f"the {engine} rule test answered {answer.status}: {answer.text}"
        assert answer.body["ok"] is True, answer.text
        assert PROBED in {line["case"] for line in answer.body["cases"]}, answer.text
        assert PROBED not in {line["case"] for line in answer.body["untested"]}, answer.text


def test_a_rule_test_leaves_the_round_s_ground_truth_unchanged(tested_round):
    assert tested_round["after_truth"] == tested_round["before_truth"], (
        "an objective changed state while only a rule test ran; the test must never reach the round's target")


def test_a_rule_test_adds_no_detection_to_the_round(tested_round):
    assert plays.marked(tested_round["after_alerts"], tested_round["live"]), (
        "a live case fired after the rule tests drew no alert, so the round's ingest proves nothing about the probes")
    seen = {alert["id"] for alert in tested_round["before_alerts"]}
    new = [alert for alert in tested_round["after_alerts"] if alert["id"] not in seen]
    from_probes = [alert for alert in new if alert["request_id"] in probe_markers() or alert["src_ip"] == "127.0.0.1"]

    assert from_probes == [], (
        f"the rule test's probes reached the round's alerts: {from_probes[:5]}; the IDS test must read its own "
        f"scratch eve.json and the WAF test its own audit log")
    assert not [alert for alert in new if alert["signature"].startswith("candidate ")], (
        "the candidate rule fired on live traffic, so the rule test wrote it to the live sensor")
