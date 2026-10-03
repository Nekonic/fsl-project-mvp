from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

import scoreboard
from api.models import Case, Session
from api.views import _loot_window
from tests.test_api_corroboration import T0, alert

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}

EXFIL_CASE = "66666666-6666-4666-8666-666666666666"


def test_a_loot_window_with_a_case_is_the_case_interval():
    session = Session.objects.create(scenario="board")
    now = timezone.now()
    case = Case.objects.create(
        session=session, case_id="c1", name="board-sqli-search", malicious=True,
        correlation="marker", started_at=now - timedelta(seconds=2), ended_at=now,
    )
    at, earliest, latest = _loot_window(session, "c1", now + timedelta(seconds=30))

    assert at == case.ended_at
    assert earliest == case.started_at - scoreboard.CLOCK_SKEW
    assert latest == case.ended_at + scoreboard.CLOCK_SKEW


def test_a_loot_window_without_a_case_uses_the_attribution_window():
    session = Session.objects.create(scenario="board")
    now = timezone.now()
    at, earliest, latest = _loot_window(session, None, now)

    assert at == now
    assert earliest == now - scoreboard.ATTRIBUTION_WINDOW
    assert latest == now + scoreboard.CLOCK_SKEW


def _start(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def _detected_exfil(client, session_id):
    Session.objects.filter(pk=session_id).update(started_at=T0 - timedelta(minutes=1))
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": EXFIL_CASE, "name": "board-sqli-search", "malicious": True,
        "expect": "SQL", "correlation": "marker",
        "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })
    with patch(
        "api.views.elastic.fetch",
        return_value=([alert(EXFIL_CASE, "FSL SQL injection attempt")], None),
    ):
        client.post_json(f"/api/sessions/{session_id}/ingest/")


def test_a_breach_row_carries_the_objective_and_the_alerts_that_saw_it(client):
    session_id = _start(client)
    _detected_exfil(client, session_id)

    submitted = client.post_json(f"/api/sessions/{session_id}/loot/", {
        "loot": [{"username": "admin", "hash": TRUTH["admin"]}],
        "case_id": EXFIL_CASE,
    })
    assert submitted.status_code == 200, submitted.content

    score = client.get(f"/api/sessions/{session_id}/score/").json()
    admin = next(b for b in score["breaches"] if b["key"] == "board-auth-user-admin")

    assert admin == {
        "key": "board-auth-user-admin", "name": "Board admin account",
        "category": "Credential Access", "difficulty": 4,
        "detected": True, "detection_ids": ["es1"],
    }


def test_a_take_whose_window_misses_the_detected_case_reads_undetected(client):
    session_id = _start(client)
    _detected_exfil(client, session_id)

    submitted = client.post_json(f"/api/sessions/{session_id}/loot/", {
        "loot": [{"username": "admin", "hash": TRUTH["admin"]}],
    })
    assert submitted.status_code == 200, submitted.content

    score = client.get(f"/api/sessions/{session_id}/score/").json()

    assert [c["verdict"] for c in score["per_case"]] == ["TP"], (
        "the exfil case drew an alert in its own window, so it is a true positive"
    )
    assert score["breaches"]
    assert all(b["detected"] is False for b in score["breaches"]), (
        "the take carried no case_id, so its window is the attribution window "
        "around submission time, which is nowhere near the detected case; the "
        "breach is scored undetected at full damage"
    )
