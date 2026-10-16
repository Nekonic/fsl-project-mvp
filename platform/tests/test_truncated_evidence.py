from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db

def a_session(client):
    from api.models import Session

    return Session.objects.create()

def ingest(client, session, truncated):
    started = timezone.now()
    alert = {
        "detection_id": "d1", "source": "suricata", "signature": "FSL SQLi",
        "severity": 2, "timestamp": started, "src_ip": "5.188.10.2",
        "marker": None, "raw": {},
    }
    with patch("api.views.elastic.fetch", return_value=([], truncated)), \
            patch("api.views.elastic.normalize_all", return_value=[alert]):
        return client.post_json(f"/api/sessions/{session.id}/ingest/", {})

def test_the_score_of_a_truncated_session_says_so(client):
    session = a_session(client)
    ingest(client, session, truncated=(5000, 9137))

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    named = [w for w in totals["warnings"] if w[0] == "score.warning.truncated"]
    assert named == [["score.warning.truncated", 5000, 9137]], totals["warnings"]

def test_one_truncated_ingest_is_not_forgotten_by_the_next_whole_one(client):
    session = a_session(client)

    ingest(client, session, truncated=(5000, 9137))
    ingest(client, session, truncated=None)
    session.refresh_from_db()

    assert session.read_of == [5000, 9137], (
        "a later ingest that happened to fit cleared the flag, so a session "
        "that once lost evidence reports itself complete. The detections that "
        "were never read are still missing"
    )

def _paged_index(started, count, size):
    stamps = [started + timedelta(seconds=n // 3) for n in range(count)]
    held = [(f"doc-{n}", {"@timestamp": stamp.isoformat()}) for n, stamp in enumerate(stamps)]
    asked = []

    def fetch(url, index, start, end, newest_first=False):
        asked.append(start)
        window = [doc for doc in held if start <= datetime.fromisoformat(doc[1]["@timestamp"]) <= end]
        return window[:size], (size, len(window)) if len(window) > size else None

    return fetch, asked

def _as_alerts(documents):
    return [{"detection_id": doc_id, "source": "suricata", "signature": "FSL SQLi", "severity": 2,
             "timestamp": datetime.fromisoformat(doc["@timestamp"]), "src_ip": "5.188.10.2",
             "marker": None, "raw": {}} for doc_id, doc in documents]

def test_an_ingest_pages_through_a_window_one_read_cannot_hold(client):
    session = a_session(client)
    fetch, asked = _paged_index(session.started_at, 23, 5)

    with patch("api.views.elastic.fetch", side_effect=fetch), \
            patch("api.views.elastic.normalize_all", side_effect=_as_alerts):
        body = client.post_json(f"/api/sessions/{session.id}/ingest/", {}).json()
    session.refresh_from_db()

    assert session.detections.count() == 23, (
        "one sqlmap case leaves more records than one read takes; the read stopped at the oldest "
        "5000 and every case fired after it scored FN (live 2026-10-13: 5000 of 13,403 read)"
    )
    assert "truncated" not in body and session.read_of is None
    assert asked == sorted(asked) and len(asked) > 1

def test_a_window_that_will_not_advance_is_still_reported_as_cut(client):
    session = a_session(client)
    flat = lambda url, index, start, end, newest_first=False: (
        [(f"same-{n}", {"@timestamp": session.started_at.isoformat()}) for n in range(2)], (2, 7))

    with patch("api.views.elastic.fetch", side_effect=flat), \
            patch("api.views.elastic.normalize_all", side_effect=_as_alerts):
        body = client.post_json(f"/api/sessions/{session.id}/ingest/", {}).json()

    assert body["truncated"] == {"read": 2, "total": 7}
