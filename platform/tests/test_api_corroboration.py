from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from redteam.harness import load_cases
from tests.sessions import open_session

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
                                                                         
                                    
CASE = "path-traversal-ftp"

@pytest.fixture
def session_id(client):
    return open_session(client)

def record(client, session_id, case_id):
    return client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": CASE, "malicious": True,
        "technique": "PathTraversal", "correlation": "marker",
        "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })

def alert(marker, signature):
    return (
        "es1",
        {
            "fsl_source": "suricata", "event_type": "alert",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "src_ip": "172.20.0.5",
            "alert": {"signature": signature, "severity": 1},
            "http": {"request_headers": [{"name": "X-FSL-Case", "value": marker}]},
        },
    )

def scored(client, session_id, signature):
    case_id = "11111111-1111-4111-8111-111111111111"
    record(client, session_id, case_id)
    with patch("api.views.elastic.fetch", return_value=([alert(case_id, signature)], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return client.get(f"/api/sessions/{session_id}/score/").json()

def test_the_right_rule_corroborates_the_true_positive(client, session_id):
    s = scored(client, session_id, "FSL path traversal attempt")

    assert s["tp"] == 1
    assert s["per_case"][0]["corroborated"] is True
    assert not any(w[0] == "score.warning.wrong_reason" for w in s["warnings"])

def test_a_true_positive_found_by_an_unrelated_rule_is_called_out(client, session_id):
                                                                            
                                                                         
                                                                           
    s = scored(client, session_id, "FSL XSS attempt - script tag or event handler")

    assert s["tp"] == 1
    assert s["per_case"][0]["detected"] is True
    assert s["per_case"][0]["corroborated"] is False
    assert any(w[0] == "score.warning.wrong_reason" and CASE in w[1]
               for w in s["warnings"])

def test_an_attack_nobody_saw_is_missed_not_caught_for_the_wrong_reason(client, session_id):
    missed = "33333333-3333-4333-8333-333333333333"
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": missed, "name": "sqli-login-bypass", "malicious": True,
        "correlation": "marker", "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })

    s = scored(client, session_id, "FSL XSS attempt - script tag or event handler")

    by_name = {c["name"]: c for c in s["per_case"]}
    assert by_name["sqli-login-bypass"]["expect"] == "SQL"
    assert by_name["sqli-login-bypass"]["verdict"] == "FN"
    assert [w for w in s["warnings"] if w[0] == "score.warning.wrong_reason"] == [
        ["score.warning.wrong_reason", CASE]
    ], (
        "the warning must name the attack an unrelated rule caught, and only "
        "that one. An attack no alert touched is a false negative; naming it "
        "here reports it twice, once as missed and once as found"
    )

def test_the_expectation_is_reported_so_the_judgement_can_be_checked(client, session_id):
    s = scored(client, session_id, "FSL path traversal attempt")

    assert s["per_case"][0]["expect"] == "traversal"

def test_a_case_the_catalogue_does_not_know_is_not_judged(client, session_id):
                                                                             
                                                                          
    case_id = "22222222-2222-4222-8222-222222222222"
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": "terminal-something", "malicious": True,
        "correlation": "marker", "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })
    with patch("api.views.elastic.fetch", return_value=([alert(case_id, "anything")], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

    s = client.get(f"/api/sessions/{session_id}/score/").json()

    assert s["per_case"][0]["detected"] is True
    assert s["per_case"][0]["corroborated"] is None
    assert not any(w[0] == "score.warning.wrong_reason" for w in s["warnings"])

CASES_DIR = Path(__file__).resolve().parents[2] / "redteam/cases"
MATCHING = "FSL path traversal attempt"

def edited_catalogue(directory):
    edited = load_cases(CASES_DIR / "default.yaml")
    for case in edited:
        if case["name"] == CASE:
            case["expect"] = "SQL"
    directory.mkdir()
    (directory / "default.yaml").write_text(yaml.safe_dump(edited))
    return str(directory)

def unparseable_catalogue(directory):
    directory.mkdir()
    (directory / "default.yaml").write_text("- name: [unclosed\n  malicious: true\n")
    return str(directory)

def judged(response):
    return response.status_code, [
        (c["name"], c["expect"], c["corroborated"]) for c in response.json()["per_case"]
    ]

def rescored_after_the_catalogue_changes(client, session_id, case_id, settings, tmp_path):
    with patch("api.views.elastic.fetch", return_value=([alert(case_id, MATCHING)], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    client.post_json(f"/api/sessions/{session_id}/close/")
    scored = [judged(client.get(f"/api/sessions/{session_id}/score/"))]
    settings.WARGAME_CASES_DIR = edited_catalogue(tmp_path / "edited")
    scored.append(judged(client.get(f"/api/sessions/{session_id}/score/")))
    settings.WARGAME_CASES_DIR = unparseable_catalogue(tmp_path / "broken")
    scored.append(judged(client.get(f"/api/sessions/{session_id}/score/")))
    return scored

def test_an_attack_fired_from_the_console_keeps_the_expectation_it_was_fired_under(
    client, session_id, settings, tmp_path
):
    with patch("api.views.harness.fire"):
        fired = client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": CASE}).json()

    scored = rescored_after_the_catalogue_changes(
        client, session_id, fired["case_id"], settings, tmp_path
    )

    assert fired["expect"] == "traversal"
    assert scored == [(200, [(CASE, "traversal", True)])] * 3, (
        "a closed session was scored against the case file as it is now: editing "
        "an expectation rewrote an old verdict, and a file that no longer parses "
        "took every old score down with it"
    )

def test_a_case_recorded_through_the_api_keeps_the_expectation_it_was_recorded_with(
    client, session_id, settings, tmp_path
):
    case_id = "44444444-4444-4444-8444-444444444444"
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": CASE, "malicious": True, "expect": "traversal",
        "correlation": "marker", "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })

    scored = rescored_after_the_catalogue_changes(client, session_id, case_id, settings, tmp_path)

    assert scored == [(200, [(CASE, "traversal", True)])] * 3
