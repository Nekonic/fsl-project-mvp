from datetime import timedelta
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

def test_an_ingest_that_could_not_read_everything_marks_the_session(client):
    session = a_session(client)

    ingest(client, session, truncated=(5000, 9137))
    session.refresh_from_db()

    assert session.read_of == [5000, 9137], (
        "elastic.fetch reported that it read 5000 of 9137 records and the "
        "session forgot. The next score is computed on part of the evidence "
        "with nothing on the page to say so"
    )

def test_the_score_of_a_truncated_session_says_so(client):
    session = a_session(client)
    ingest(client, session, truncated=(5000, 9137))

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    named = [w for w in totals["warnings"] if w[0] == "score.warning.truncated"]
    assert named == [["score.warning.truncated", 5000, 9137]], totals["warnings"]

def test_a_session_read_whole_says_nothing(client):
    session = a_session(client)
    ingest(client, session, truncated=None)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert not [w for w in totals["warnings"] if w[0] == "score.warning.truncated"]

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
