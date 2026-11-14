def test_ground_truth_contains_both_labels(full_run):
    cases = full_run["cases"]

    assert any(c["malicious"] for c in cases)
    assert any(not c["malicious"] for c in cases), (
        "without benign cases, a rule that blocks everything scores perfectly"
    )


def test_both_engines_produce_detections(full_run):
    detections = full_run["detections"]

    assert {d["source"] for d in detections} == {"suricata", "modsecurity"}

def test_criterion_3_true_positive_is_not_zero(score):
    assert score["tp"] > 0, f"no attack was detected at all. Score: {score}"

def test_criterion_3_true_negative_is_not_zero(score):
    assert score["tn"] > 0, (
        f"all benign traffic raised an alert, so scoring false positives is "
        f"meaningless. Score: {score}"
    )

def test_score_has_no_pipeline_warnings(score):
    pipeline_warnings = [
        w for w in score["warnings"]
        if w[0] in ("score.warning.no_marker", "score.warning.no_source_ip")
    ]

    assert not pipeline_warnings, pipeline_warnings

def test_detections_are_spread_across_cases(score):
    owners = [len(c["detection_ids"]) for c in score["per_case"] if c["detected"]]

    assert len(owners) > 1, (
        f"only one case was detected; alerts may have collapsed onto one case. "
        f"Score: {score}"
    )

def test_the_stack_does_not_attack_itself(full_run):
    rows = full_run["detections"]

    own = [
        d["signature"] for d in rows
        if d["src_ip"] in ("127.0.0.1", "::1")
        or "numeric IP address" in d["signature"]
    ]

    assert own == [], (
        f"the stack raised alerts on traffic it sent to itself: "
        f"{sorted(set(own))}. Last time this was the WAF's health check "
        f"curling a numeric host every ten seconds, tripping CRS 920350 and "
        f"filing a false positive against the defence it is scoring.\n"
        f"Before hunting the code: a session's window reaches a minute either "
        f"side of the session, so this also goes red on residue from whatever "
        f"used the range in the minute before this run. Check whether the "
        f"signature is still being produced now, not only that it is in here."
    )

def test_the_real_rule_set_still_gets_the_credit(score):
    credited = [
        c["name"] for c in score["per_case"]
        if c["malicious"] and c["expect"] and c["corroborated"] is True
    ]

    assert credited, (
        f"the baseline defence corroborates nothing either, so the check now "
        f"rejects every rule set rather than only indiscriminate ones: "
        f"{[(c['name'], c['corroborated']) for c in score['per_case'] if c['malicious']]}"
    )
