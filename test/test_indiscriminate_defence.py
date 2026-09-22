import pytest
import requests

from conftest import PLATFORM_URL

CATCH_ALL = (
    'alert http any any -> any any (msg:"SQL XSS traversal Restricted File"; '
    'flow:established,to_server; http.uri; content:"/"; sid:9009997; rev:1;)\n'
)
CASES = [
    "sqli-login-bypass", "xss-img-onerror", "path-traversal-ftp",
    "normal-product-search", "normal-login-attempt",
]

def rules():
    return requests.get(f"{PLATFORM_URL}/api/rules/", timeout=60).json()["content"]

def apply_rules(content):
    applied = requests.post(
        f"{PLATFORM_URL}/api/rules/apply/", json={"content": content}, timeout=180
    )
    assert applied.ok, applied.text

def fire_and_score(session_id):
    for name in CASES:
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": name}, timeout=300,
        )
        assert sent.status_code == 201, sent.text

    from conftest import score_when_ready

    return score_when_ready(
        session_id, lambda totals: totals["tp"] > 0 and totals["fp"] > 0
    )

def signatures(session_id):
    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    rows = listed if isinstance(listed, list) else listed["detections"]
    return {d["detection_id"]: d["signature"] for d in rows}

def indiscriminate(totals, sigs):
    found = set()
    for case in totals["per_case"]:
        if not case["malicious"]:
            found |= {sigs[i] for i in case["detection_ids"] if i in sigs}
    return found

@pytest.fixture(scope="module")
def block_everything(stack_is_up, baseline_rules):
    apply_rules(CATCH_ALL)
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    try:
        totals = fire_and_score(session_id)
        yield totals, signatures(session_id)
    finally:
        apply_rules(baseline_rules)

def test_the_experiment_is_valid_at_all(block_everything):
    totals, sigs = block_everything

    assert totals["fp"] > 0 and totals["tp"] > 0, (
        f"the catch-all rule did not fire on both attacks and benign traffic, "
        f"so nothing below proves anything: {totals['tp']}/{totals['fp']}"
    )
    assert indiscriminate(totals, sigs), (
        "no signature fired on both, so there is no indiscriminate defence here"
    )

def test_nothing_is_credited_to_a_signature_that_also_fires_on_benign_traffic(
    block_everything,
):
    totals, sigs = block_everything
    noise = indiscriminate(totals, sigs)

    for case in totals["per_case"]:
        if not (case["malicious"] and case["corroborated"] is True):
            continue
        own = {sigs[i] for i in case["detection_ids"] if i in sigs}
        assert own - noise, (
            f"{case['name']} was credited with a real detection, and every "
            f"signature it drew also fired on traffic meant to pass: {own}. "
            f"The defence writes that text, so a block-everything rule set "
            f"wins the one number meant to stop it"
        )

def test_a_defence_with_nothing_but_noise_is_called_out(block_everything):
    totals, sigs = block_everything
    noise = indiscriminate(totals, sigs)

    only_noise = [
        c["name"] for c in totals["per_case"]
        if c["malicious"] and c["expect"]
        and not ({sigs[i] for i in c["detection_ids"] if i in sigs} - noise)
    ]

    assert only_noise, (
        "every attack drew at least one discriminating alert, so this run "
        "cannot show the check biting - ModSecurity caught them all"
    )
    for name in only_noise:
        case = next(c for c in totals["per_case"] if c["name"] == name)
        assert case["corroborated"] is False, (
            f"{name} drew nothing but indiscriminate alerts and still reports "
            f"corroborated={case['corroborated']!r}"
        )
    assert any(
        w[0] == "score.warning.wrong_reason" for w in totals["warnings"]
    ), totals["warnings"]

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
