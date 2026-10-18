from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.sessions import open_session

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
ATTACK = "11111111-1111-4111-8111-111111111111"
BENIGN = "22222222-2222-4222-8222-222222222222"

def fire(client, session_id, case_id, name, malicious):
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id,
        "name": name,
        "malicious": malicious,
        "correlation": "marker",
        "source_ip": "172.20.0.5",
        "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })

@pytest.fixture
def session_with_cases(client):
    session_id = open_session(client)
    fire(client, session_id, ATTACK, "sqli", True)
    fire(client, session_id, BENIGN, "search", False)
    return session_id

def es_alert(marker, doc_id="es1"):
    return (
        doc_id,
        {
            "event": {"module": "suricata"},
            "event_type": "alert",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "src_ip": "172.20.0.5",
            "alert": {"signature": "SQLi", "severity": 1},
            "http": {"request_headers": [{"name": "X-Request-ID", "value": marker}]},
        },
    )

def ingest(client, session_id, alerts):
    with patch("api.views.elastic.fetch", return_value=(alerts, None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

@pytest.mark.parametrize("alerts, counts, verdicts", [
    ([es_alert(ATTACK)], (1, 0, 0, 1), {"sqli": "TP", "search": "TN"}),
    ([es_alert(ATTACK), es_alert(BENIGN, doc_id="es2")], (1, 1, 0, 0), {"sqli": "TP", "search": "FP"}),
    ([], (0, 0, 1, 1), {"sqli": "FN", "search": "TN"}),
])
def test_the_score_counts_each_case_by_the_alerts_its_marker_drew(client, session_with_cases, alerts, counts, verdicts):
    ingest(client, session_with_cases, alerts)

    score = client.get(f"/api/sessions/{session_with_cases}/score/").json()

    assert (score["tp"], score["fp"], score["fn"], score["tn"]) == counts
    assert {entry["name"]: entry["verdict"] for entry in score["per_case"]} == verdicts

def test_a_brief_score_counts_the_alerts_per_case_without_listing_their_ids(client, session_with_cases):
    ingest(client, session_with_cases, [es_alert(ATTACK), es_alert(ATTACK, doc_id="es2")])

    full = client.get(f"/api/sessions/{session_with_cases}/score/").json()
    brief = client.get(f"/api/sessions/{session_with_cases}/score/?brief=1").json()
    attack = next(entry for entry in brief["per_case"] if entry["name"] == "sqli")

    assert sorted(next(entry for entry in full["per_case"] if entry["name"] == "sqli")["detection_ids"]) == ["es1", "es2"]
    assert attack["detections"] == 2 and "detection_ids" not in attack
    assert all("detection_ids" not in entry for entry in brief["breaches"])
    assert {key: value for key, value in brief.items() if key not in ("per_case", "breaches")} == \
        {key: value for key, value in full.items() if key not in ("per_case", "breaches")}

def test_reading_the_score_writes_nothing(client, session_with_cases):
    from django.db import connection

    ingest(client, session_with_cases, [es_alert(ATTACK)])

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
