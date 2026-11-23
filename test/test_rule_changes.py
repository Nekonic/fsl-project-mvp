import plays


def test_criterion_4_adding_a_rule_moves_the_score(rules_session):
    live, posted = rules_session["noisy_rules"]
    assert live == posted, "the round's start posture did not reach the sensor"

    benign = plays.per_case(rules_session["after_noisy"])["board-normal-search"]
    assert benign["verdict"] == "fp", (
        f"a rule hitting 'release' was added and the benign search for 'release notes' "
        f"was not scored a false positive: {benign}"
    )


def test_invalid_rule_is_rejected_and_not_applied(rules_session):
    shell = rules_session["invalid"].shell
    assert not rules_session["invalid"].ok and shell["exit_code"] not in (0, None, 255), rules_session["invalid"].text
    assert "error" in (shell["stdout"] + shell["stderr"]).lower(), (
        f"sudo suricata -T refused the rule without saying why: {shell}")
    assert rules_session["rules_after_invalid"] == rules_session["rules_before_invalid"]
