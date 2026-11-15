def test_criterion_4_adding_a_rule_moves_the_score(rules_session):
    assert rules_session["noisy"].ok, rules_session["noisy"].text

    after = rules_session["after"]
    benign = next(case for case in after["per_case"] if case["case_id"] == rules_session["noisy_benign"])
    assert benign["verdict"] == "FP", (
        f"a rule hitting 'release' was added and the benign search for 'release notes' "
        f"was not scored a false positive: {benign}"
    )

def test_invalid_rule_is_rejected_and_not_applied(rules_session):
    assert rules_session["invalid"].status_code == 400
    assert rules_session["rules_after_invalid"] == rules_session["rules_before_invalid"]
