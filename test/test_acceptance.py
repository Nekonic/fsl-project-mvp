import requests

from conftest import PLATFORM_URL, target_code
from range import SCORER, run

def test_criterion_1_services_answer(standing_stack):
    assert requests.get(
        f"{PLATFORM_URL}/api/rules/", params={"session": standing_stack}, timeout=5
    ).ok
    assert 0 < target_code() < 500
    assert run(SCORER, [
        "python", "-c",
        "import os,urllib.request; urllib.request.urlopen(os.environ.get("
        "'ELASTIC_URL', 'http://elasticsearch:9200') + '/_cluster/health', timeout=5)",
    ]).ok

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

def test_the_score_accounts_for_every_alert_it_ingested(session_id, score):
    rows = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    attributed = sum(len(c["detection_ids"]) for c in score["per_case"])

    assert attributed + score["unattributed"] == len(rows), (
        f"{len(rows)} alerts ingested, {attributed} attributed to a case, "
        f"{score['unattributed']} reported unplaced. The difference is "
        f"evidence that entered no number and appears nowhere"
    )

def test_the_stack_does_not_attack_itself(session_id, score):
    rows = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()

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
