import plays


def test_criterion_4_adding_a_rule_moves_the_score(rules_session):
    assert rules_session["noisy"].ok, rules_session["noisy"].text

    benign = plays.per_case(rules_session["after_noisy"])["board-normal-search"]
    assert benign["verdict"] == "fp", (
        f"a rule hitting 'release' was added and the benign search for 'release notes' "
        f"was not scored a false positive: {benign}"
    )


def test_invalid_rule_is_rejected_and_not_applied(rules_session):
    assert rules_session["checked_invalid"].ok and rules_session["checked_invalid"].body["ok"] is False
    assert rules_session["invalid"].status == 422 and "suricata_syntax" in rules_session["invalid"].codes, (
        rules_session["invalid"].text)
    assert rules_session["rules_after_invalid"] == rules_session["rules_before_invalid"]
