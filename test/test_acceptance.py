"""Check the acceptance criteria from section 9 of the design document.

Criterion 3 (TP > 0 and TN > 0) is where this MVP can be falsified. TP of zero
means alert-to-case correlation failed; TN of zero means scoring false
positives is meaningless.
"""

import requests

from conftest import PLATFORM_URL, TARGET_URL, run_redteam, score_when_ready

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"FSL deliberate false positive"; '
    'http.uri; content:"apple"; nocase; sid:9009999; rev:1;)\n'
)


def test_criterion_1_services_answer():
    """Criterion 1: the stack is up."""
    assert requests.get(f"{PLATFORM_URL}/api/rules/", timeout=5).ok
    assert requests.get(TARGET_URL, timeout=5).status_code < 500
    assert requests.get("http://localhost:9200/_cluster/health", timeout=5).ok


def test_criterion_2_redteam_run_produces_a_closed_session(session_id):
    """Criterion 2: the red team finishes and yields a session number."""
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
    """Without markers on alerts, correlation is impossible at all."""
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

    assert detections, "not a single alert was ingested"
    assert any(d["marker"] for d in detections), (
        "no alert carries X-FSL-Case. Check the eve-log http dump-all-headers "
        "setting in deploy/suricata/suricata.yaml."
    )


def test_both_engines_produce_detections(session_id, score):
    """Suricata and ModSecurity must both be alive."""
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

    assert {d["source"] for d in detections} == {"suricata", "modsecurity"}


def test_criterion_3_true_positive_is_not_zero(score):
    """Criterion 3a: some attack is detected. Zero here breaks the hypothesis."""
    assert score["tp"] > 0, f"no attack was detected at all. Score: {score}"


def test_criterion_3_true_negative_is_not_zero(score):
    """Criterion 3b: some benign traffic passes quietly."""
    assert score["tn"] > 0, (
        f"all benign traffic raised an alert, so scoring false positives is "
        f"meaningless. Score: {score}"
    )


def test_score_has_no_pipeline_warnings(score):
    """A score is only trustworthy without pipeline-failure warnings."""
    pipeline_warnings = [
        w for w in score["warnings"] if "marker" in w or "source_ip" in w
    ]

    assert not pipeline_warnings, pipeline_warnings


def test_detections_are_spread_across_cases(session_id, score):
    """Under keep-alive, a flow's alerts must not all land on the first case."""
    owners = [len(c["detection_ids"]) for c in score["per_case"] if c["detected"]]

    assert len(owners) > 1, (
        f"only one case was detected; alerts may have collapsed onto one case. "
        f"Score: {score}"
    )


def test_criterion_4_adding_a_rule_moves_the_score():
    """Criterion 4: adding a rule moves the next run's score as predicted.

    A rule that only hits normal search should raise false positives.
    """
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
    """Rules that fail validation are never written to the file."""
    before = requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"]

    response = requests.post(
        f"{PLATFORM_URL}/api/rules/apply/",
        json={"content": "this is not a rule"},
        timeout=120,
    )

    assert response.status_code == 400
    assert requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"] == before
