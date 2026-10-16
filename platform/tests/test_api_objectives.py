from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Objective, Session

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}

EXFIL_CASE = "66666666-6666-4666-8666-666666666666"


def _start(client, truth=None):
    with patch("api.views.loot.ground_truth", return_value=dict(truth or TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def _blind(client):
    return Session.objects.create(scenario="board", baseline=None).pk


def _fire_exfil(client, session_id, case_id=EXFIL_CASE):
    now = timezone.now()
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": "board-sqli-search", "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })
    return case_id


def _submit(client, session_id, names, case_id=None):
    body = {"loot": [{"username": n, "hash": TRUTH[n]} for n in names]}
    if case_id is not None:
        body["case_id"] = case_id
    return client.post_json(f"/api/sessions/{session_id}/loot/", body)


def test_an_objective_taken_during_the_session_is_recorded(client):
    session_id = _start(client)
    _fire_exfil(client, session_id)

    _submit(client, session_id, ["admin"])

    taken = set(Objective.objects.filter(session_id=session_id).values_list("key", flat=True))
    assert "board-auth-user-admin" in taken and "board-auth-user-full" not in taken


def test_loot_from_another_sessions_snapshot_credits_nothing(client):
    session_id = _start(client)
    _fire_exfil(client, session_id)

    old_salts = [{"username": n, "hash": TRUTH[n][::-1]} for n in TRUTH]
    response = client.post_json(f"/api/sessions/{session_id}/loot/", {"loot": old_salts})

    assert response.json()["credited"] == []
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_the_same_loot_twice_credits_each_tier_once(client):
    session_id = _start(client)
    _fire_exfil(client, session_id)

    _submit(client, session_id, ["admin", "jiwoo", "minseo"])
    second = _submit(client, session_id, ["admin", "jiwoo", "minseo"])

    assert second.json()["objectives"] == 0
    assert Objective.objects.filter(session_id=session_id).count() == 3


def test_a_board_opened_blind_refuses_loot_with_409(client):
    session_id = _blind(client)
    assert Session.objects.get(pk=session_id).baseline is None
    _fire_exfil(client, session_id)

    response = _submit(client, session_id, ["admin"])

    assert response.status_code == 409
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_the_case_end_is_the_recorded_solve_time(client):
    session_id = _start(client)
    case_id = _fire_exfil(client, session_id)

    _submit(client, session_id, ["admin"], case_id=case_id)

    case = Session.objects.get(pk=session_id).cases.get(case_id=case_id)
    recorded = Objective.objects.get(session_id=session_id, key="board-auth-user-admin")
    assert recorded.achieved_at == case.ended_at
