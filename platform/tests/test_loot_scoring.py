from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Session
from tests.test_api_corroboration import T0, alert

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}
EXFIL = "44444444-4444-4444-8444-444444444444"


def _board_with_detected_exfil(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        session_id = client.post_json(
            "/api/sessions/", {"scenario": "board"}
        ).json()["id"]
    Session.objects.filter(pk=session_id).update(started_at=T0 - timedelta(minutes=1))
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": EXFIL, "name": "board-members-json", "malicious": True,
        "expect": "", "correlation": "marker",
        "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })
    with patch("api.views.elastic.fetch", return_value=([alert(EXFIL, "FSL exfil")], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return session_id


def test_a_credited_loot_objective_reaches_the_scoreboard_and_game(client):
    session_id = _board_with_detected_exfil(client)
    rows = [{"username": n, "hash": TRUTH[n]} for n in TRUTH]
    client.post_json(f"/api/sessions/{session_id}/loot/",
                     {"loot": rows, "case_id": EXFIL})

    client.post_json(f"/api/sessions/{session_id}/close/")
    score = client.get(f"/api/sessions/{session_id}/score/").json()

    assert score["objectives"]["objectives"] == 3
    assert {b["key"] for b in score["breaches"]} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert score["game"]["revealed"] is True
    assert score["game"]["attacker"] > 0


def test_detected_follows_the_attributed_exfil_case_not_the_quiet_submission(client):
    session_id = _board_with_detected_exfil(client)
    rows = [{"username": "admin", "hash": TRUTH["admin"]}]
    client.post_json(f"/api/sessions/{session_id}/loot/",
                     {"loot": rows, "case_id": EXFIL})

    score = client.get(f"/api/sessions/{session_id}/score/").json()
    admin = next(b for b in score["breaches"] if b["key"] == "board-auth-user-admin")

    assert admin["detected"] is True, (
        "the loot objective must inherit detection from the correlated exfil "
        "case, not from whether the quiet submission itself was alerted"
    )
    assert admin["detection_ids"] == ["es1"]
