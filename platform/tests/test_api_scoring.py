from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ingest.elastic import ElasticUnavailable

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
ATTACK = "11111111-1111-4111-8111-111111111111"
BENIGN = "22222222-2222-4222-8222-222222222222"

@pytest.fixture
def session_with_cases(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    for case_id, name, malicious in ((ATTACK, "sqli", True), (BENIGN, "search", False)):
        client.post_json(f"/api/sessions/{session_id}/cases/", {
                "case_id": case_id,
                "name": name,
                "malicious": malicious,
                "correlation": "marker",
                "source_ip": "172.20.0.5",
                "started_at": T0.isoformat(),
                "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
            },
        )
    return session_id

def es_alert(marker, doc_id="es1"):
    return (
        doc_id,
        {
            "fsl_source": "suricata",
            "event_type": "alert",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "src_ip": "172.20.0.5",
            "alert": {"signature": "SQLi", "severity": 1},
            "http": {"request_headers": [{"name": "X-FSL-Case", "value": marker}]},
        },
    )

def test_ingest_stores_detections(client, session_with_cases):
    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK)]):
        response = client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    assert response.status_code == 200
    assert response.json()["ingested"] == 1

    listed = client.get(f"/api/sessions/{session_with_cases}/detections/")
    assert len(listed.json()) == 1
    assert listed.json()[0]["marker"] == ATTACK

def test_ingest_skips_non_alert_documents(client, session_with_cases):
    noise = ("es9", {"fsl_source": "suricata", "event_type": "http"})
    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK), noise]):
        response = client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    assert response.json()["ingested"] == 1
    assert response.json()["skipped"] == 1

def test_ingest_is_idempotent(client, session_with_cases):
    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK)]):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")
        second = client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    assert second.json()["ingested"] == 0
    assert len(client.get(f"/api/sessions/{session_with_cases}/detections/").json()) == 1

def test_ingest_reports_503_when_elasticsearch_is_unreachable(client, session_with_cases):
    with patch("api.views.elastic.fetch", side_effect=ElasticUnavailable("index missing")):
        response = client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    assert response.status_code == 503
    assert "index missing" in response.json()["detail"]

def test_score_counts_true_positive_and_true_negative(client, session_with_cases):
    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK)]):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    response = client.get(f"/api/sessions/{session_with_cases}/score/")

    assert response.status_code == 200
    assert response.json()["tp"] == 1
    assert response.json()["tn"] == 1
    assert response.json()["fp"] == 0
    assert response.json()["fn"] == 0

def test_score_counts_false_positive_when_benign_case_alerts(client, session_with_cases):
    with patch(
        "api.views.elastic.fetch",
        return_value=[es_alert(ATTACK), es_alert(BENIGN, doc_id="es2")],
    ):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    response = client.get(f"/api/sessions/{session_with_cases}/score/")

    assert response.json()["fp"] == 1
    assert response.json()["false_positive_rate"] == pytest.approx(1.0)

def test_score_counts_false_negative_when_attack_is_silent(client, session_with_cases):
    with patch("api.views.elastic.fetch", return_value=[]):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    response = client.get(f"/api/sessions/{session_with_cases}/score/")

    assert response.json()["fn"] == 1
    assert response.json()["tn"] == 1

def test_score_includes_per_case_verdicts(client, session_with_cases):
    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK)]):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    per_case = client.get(f"/api/sessions/{session_with_cases}/score/").json()["per_case"]

    by_name = {entry["name"]: entry for entry in per_case}
    assert by_name["sqli"]["verdict"] == "TP"
    assert by_name["search"]["verdict"] == "TN"

def test_reading_the_score_writes_nothing(client, session_with_cases):
    from django.db import connection

    with patch("api.views.elastic.fetch", return_value=[es_alert(ATTACK)]):
        client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    before = _row_counts(connection)
    for _ in range(3):
        client.get(f"/api/sessions/{session_with_cases}/score/")

    assert _row_counts(connection) == before, (
        "a GET grew the database, so looking at the scoreboard changes the "
        "record it is reporting"
    )

def _row_counts(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'api_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        counts = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
    return counts

def test_score_on_session_without_cases_warns_about_benign(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    response = client.get(f"/api/sessions/{session_id}/score/")

    assert response.status_code == 200
    assert any("benign" in w for w in response.json()["warnings"])

def test_ingest_skipped_counts_documents_not_alerts(client, session_with_cases):
                                                                            
                                                               
    modsec = (
        "m1",
        {
            "fsl_source": "modsecurity",
            "transaction": {
                "time_stamp": "Fri Sep 18 12:00:01 2026",
                "client_ip": "172.20.0.5",
                "request": {"headers": {"X-FSL-Case": ATTACK}},
                "messages": [{"message": "first"}, {"message": "second"}],
            },
        },
    )
    noise = ("n1", {"fsl_source": "suricata", "event_type": "http"})

    with patch("api.views.elastic.fetch", return_value=[modsec, noise]):
        response = client.post_json(f"/api/sessions/{session_with_cases}/ingest/")

    assert response.json()["ingested"] == 2
    assert response.json()["skipped"] == 1
