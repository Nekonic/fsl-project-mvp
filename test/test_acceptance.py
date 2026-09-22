import requests

from conftest import PLATFORM_URL, TARGET_URL, run_redteam, score_when_ready

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"FSL deliberate false positive"; '
    'http.uri; content:"apple"; nocase; sid:9009999; rev:1;)\n'
)

def test_criterion_1_services_answer():
    assert requests.get(f"{PLATFORM_URL}/api/rules/", timeout=5).ok
    assert requests.get(TARGET_URL, timeout=5).status_code < 500
    assert requests.get("http://localhost:9200/_cluster/health", timeout=5).ok

def test_criterion_2_redteam_run_produces_a_closed_session(session_id):
    response = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/")

    assert response.ok
    assert response.json()["ended_at"] is not None

def test_ground_truth_contains_both_labels(session_id):
    cases = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/cases/").json()

    assert any(c["malicious"] for c in cases)
    assert any(not c["malicious"] for c in cases), (
        "without benign cases, a rule that blocks everything scores perfectly"
    )

def test_detections_carry_case_markers(session_id, score):
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

    assert detections, "not a single alert was ingested"
    assert any(d["marker"] for d in detections), (
        "no alert carries X-FSL-Case. Check the eve-log http dump-all-headers "
        "setting in deploy/suricata/suricata.yaml."
    )

def test_both_engines_produce_detections(session_id, score):
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

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

def test_detections_are_spread_across_cases(session_id, score):
    owners = [len(c["detection_ids"]) for c in score["per_case"] if c["detected"]]

    assert len(owners) > 1, (
        f"only one case was detected; alerts may have collapsed onto one case. "
        f"Score: {score}"
    )

def test_criterion_4_adding_a_rule_moves_the_score():
    original = requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"]

    try:
        applied = requests.post(
            f"{PLATFORM_URL}/api/rules/apply/",
            json={"content": original + NOISY_RULE},
            timeout=120,
        )
        assert applied.ok, applied.text

        after = score_when_ready(run_redteam(), until=lambda s: s["fp"] > 0)
        assert after["fp"] > 0, (
            f"a rule hitting 'apple' was added but no false positive was "
            f"scored. Score: {after}"
        )
    finally:
        requests.post(
            f"{PLATFORM_URL}/api/rules/apply/", json={"content": original}, timeout=120
        )

def test_invalid_rule_is_rejected_and_not_applied():
    before = requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"]

    response = requests.post(
        f"{PLATFORM_URL}/api/rules/apply/",
        json={"content": "this is not a rule"},
        timeout=120,
    )

    assert response.status_code == 400
    assert requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"] == before

def test_the_score_accounts_for_every_alert_it_ingested(session_id, score):
    import requests

    from conftest import PLATFORM_URL

    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    rows = listed if isinstance(listed, list) else listed["detections"]
    attributed = sum(len(c["detection_ids"]) for c in score["per_case"])

    assert attributed + score["unattributed"] == len(rows), (
        f"{len(rows)} alerts ingested, {attributed} attributed to a case, "
        f"{score['unattributed']} reported unplaced. The difference is "
        f"evidence that entered no number and appears nowhere"
    )

def test_the_stack_does_not_attack_itself(session_id, score):
    import requests

    from conftest import PLATFORM_URL

    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    rows = listed if isinstance(listed, list) else listed["detections"]

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

def test_the_false_positive_denominator_is_the_benign_case_count(score):
    benign = [c for c in score["per_case"] if not c["malicious"]]

    assert score["benign_cases"] == len(benign) == score["fp"] + score["tn"]
