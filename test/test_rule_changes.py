def test_criterion_4_adding_a_rule_moves_the_score(rules_session):
    assert rules_session["noisy"].ok, rules_session["noisy"].text

    after = rules_session["after"]
    assert after["fp"] > 0, (
        f"a rule hitting 'release' was added but no false positive was "
        f"scored. Score: {after}"
    )

def test_invalid_rule_is_rejected_and_not_applied(rules_session):
    assert rules_session["invalid"].status_code == 400
    assert rules_session["rules_after_invalid"] == rules_session["rules_before_invalid"]
