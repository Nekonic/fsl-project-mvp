from collections import Counter

import plays
from shared_sessions import CATCH_ALL_BENIGN, CONTROL, SQLMAP, benign_names


def test_ground_truth_contains_both_labels(full_run):
    scored = set(plays.per_case(full_run["score"]))

    assert scored & set(full_run["markers"])
    assert scored & benign_names(), (
        "without benign cases, a rule that blocks everything scores perfectly"
    )


def test_criterion_3_true_positive_is_not_zero(score):
    assert plays.totals(score)["tp"] > 0, f"no attack was detected at all. Score: {score}"


def test_criterion_3_true_negative_is_not_zero(score):
    assert plays.totals(score)["tn"] > 0, (
        f"all benign traffic raised an alert, so scoring false positives is "
        f"meaningless. Score: {score}"
    )


def test_every_case_the_attack_bot_fired_is_one_decision_in_the_score(full_run):
    lines = full_run["score"]["outcomes"]["per_case"]
    named = Counter(line["case"] for line in lines)
    sqlmap = [line for line in lines if line["case"] == SQLMAP]

    assert {name: named[name] for name in full_run["markers"]} == dict.fromkeys(full_run["markers"], 1), named
    assert len(sqlmap) == 1 and sqlmap[0]["alerts"] > 1, (
        f"{SQLMAP} sends many requests through the WAF and must draw many alerts on one line: {sqlmap}")
    assert sum(plays.totals(full_run["score"]).values()) == len(lines), plays.totals(full_run["score"])
    assert sum(line["alerts"] for line in lines) > len(lines), "the totals count alerts, not cases"


def test_detections_are_spread_across_cases(score):
    owners = [line["case"] for line in score["outcomes"]["per_case"] if line["alerts"] > 0]

    assert len(owners) > 1, (
        f"only one case was detected; alerts may have collapsed onto one case. "
        f"Score: {score}"
    )


def test_the_stack_does_not_attack_itself(full_run):
    own = sorted({(alert["src_ip"], alert["rule"], alert["signature"]) for alert in full_run["alerts"]
                  if alert["src_ip"] in full_run["own_sources"]})
    numeric_host = [line for line in own if line[1] == "920350"]

    assert own == [], (
        f"the stack raised alerts on traffic it sent from its own addresses {sorted(full_run['own_sources'])}: "
        f"{own}. Rule 920350 among them ({numeric_host}) is the WAF's health check curling a numeric host, "
        f"filing a false positive against the defence it is scoring."
    )


def test_the_real_rule_set_still_gets_the_credit(full_run):
    expecting = {case["name"] for case in full_run["declared"] if case.get("malicious") and case.get("expect")}
    lines = plays.per_case(full_run["score"])
    credited = [name for name in expecting if lines.get(name, {}).get("corroborated") is True]

    assert credited, (
        f"the baseline defence corroborates nothing either, so the check now "
        f"rejects every rule set rather than only indiscriminate ones: "
        f"{[(name, lines.get(name, {}).get('corroborated')) for name in sorted(expecting)]}"
    )


def test_a_true_positive_whose_alert_does_not_name_the_mechanism_is_not_corroborated(rules_session):
    lines = plays.per_case(rules_session["after_generic"])

    assert any(name in lines for name in CATCH_ALL_BENIGN), "no benign case ran beside the generic rule"
    assert lines[CONTROL]["verdict"] == "tp" and lines[CONTROL]["corroborated"] is False, (
        f"a rule whose message says 'generic probe' caught the SQL injection and was credited with naming it: "
        f"{lines[CONTROL]}")


def test_benign_traffic_comes_from_the_infra_not_the_attacker(rules_session):
    attack_markers = set(rules_session["noisy_markers"].values())
    benign = [alert for alert in rules_session["noisy_alerts"]
              if alert["request_id"] and alert["request_id"] not in attack_markers]
    processes = rules_session["attacker_processes"].splitlines()

    assert benign, "no alert carried a benign marker, so nothing shows where benign traffic comes from"
    assert not [alert for alert in benign if alert["src_ip"] in rules_session["noisy_origins"]], (
        f"benign requests left from an attack origin: {[a for a in benign if a['src_ip'] in rules_session['noisy_origins']][:5]}")
    assert not [line for line in processes if "users.py" in line or line.split(" ", 1)[0] == "cr-users"], (
        f"the attacker box runs the customers' program: {processes}")
