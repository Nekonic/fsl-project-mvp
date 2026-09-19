"""A true positive is not automatically evidence that the defence worked.

An alert inside the window is an alert inside the window. Whether it had
anything to do with the attack is a separate question, and one the score used
to answer by assumption.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
# A case the catalogue declares an expectation for: it should be found by
# something that mentions traversal.
CASE = "path-traversal-ftp"


@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]


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
    with patch("api.views.elastic.fetch", return_value=[alert(case_id, signature)]):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return client.get(f"/api/sessions/{session_id}/score/").json()


def test_the_right_rule_corroborates_the_true_positive(client, session_id):
    s = scored(client, session_id, "FSL path traversal attempt")

    assert s["tp"] == 1
    assert s["per_case"][0]["corroborated"] is True
    assert not any("wrong reason" in w for w in s["warnings"])


def test_a_true_positive_found_by_an_unrelated_rule_is_called_out(client, session_id):
    # Still a true positive by the arithmetic. But the only thing that fired
    # was an XSS rule, and this is a path traversal - so the score saying
    # "detected" would be claiming something the evidence does not support.
    s = scored(client, session_id, "FSL XSS attempt - script tag or event handler")

    assert s["tp"] == 1
    assert s["per_case"][0]["detected"] is True
    assert s["per_case"][0]["corroborated"] is False
    assert any("wrong reason" in w and CASE in w for w in s["warnings"])


def test_the_expectation_is_reported_so_the_judgement_can_be_checked(client, session_id):
    s = scored(client, session_id, "FSL path traversal attempt")

    assert s["per_case"][0]["expect"] == "traversal"


def test_a_case_the_catalogue_does_not_know_is_not_judged(client, session_id):
    # Terminal windows have no declared mechanism. Reporting them as detected
    # for the wrong reason would be an accusation the data cannot support.
    case_id = "22222222-2222-4222-8222-222222222222"
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": "terminal-something", "malicious": True,
        "correlation": "marker", "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })
    with patch("api.views.elastic.fetch", return_value=[alert(case_id, "anything")]):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

    s = client.get(f"/api/sessions/{session_id}/score/").json()

    assert s["per_case"][0]["detected"] is True
    assert s["per_case"][0]["corroborated"] is None
    assert not any("wrong reason" in w for w in s["warnings"])
