import plays
from shared_sessions import benign_names


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
    lines = [line["case"] for line in full_run["score"]["outcomes"]["per_case"]]

    assert set(full_run["markers"]) <= set(lines), sorted(set(full_run["markers"]) - set(lines))
    assert full_run["score"]["outcomes"]["note"] == "one_case_one_decision"


def test_detections_are_spread_across_cases(score):
    owners = [line["case"] for line in score["outcomes"]["per_case"] if line["alerts"] > 0]

    assert len(owners) > 1, (
        f"only one case was detected; alerts may have collapsed onto one case. "
        f"Score: {score}"
    )


def test_the_stack_does_not_attack_itself(full_run):
    own = [
        alert["signature"] for alert in full_run["alerts"]
        if alert["src_ip"] in ("127.0.0.1", "::1")
        or "numeric IP address" in alert["signature"]
    ]

    assert own == [], (
        f"the stack raised alerts on traffic it sent to itself: "
        f"{sorted(set(own))}. Last time this was the WAF's health check "
        f"curling a numeric host every ten seconds, tripping CRS 920350 and "
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
