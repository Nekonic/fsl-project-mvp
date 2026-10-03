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


def start(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def fire_exfil(client, session_id, case_id="22222222-2222-4222-8222-222222222222"):
    now = timezone.now()
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": "board-members-json", "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })
    return case_id


def submit(client, session_id, rows, case_id=None):
    body = {"loot": rows}
    if case_id is not None:
        body["case_id"] = case_id
    return client.post_json(f"/api/sessions/{session_id}/loot/", body)


def rows_for(*names):
    return [{"username": n, "hash": TRUTH[n]} for n in names]


def test_a_whole_dump_credits_partial_admin_and_full(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert response.status_code == 200, response.content
    assert set(response.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert response.json()["coverage"] == 1.0
    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }


def test_one_non_admin_row_fires_only_partial(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("jiwoo"))

    assert response.json()["credited"] == ["board-auth-user-partial"]


def test_the_admin_hash_fires_partial_and_admin(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("admin"))

    assert set(response.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin"
    }


def test_fabricated_and_plaintext_loot_credits_nothing(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    fabricated = submit(client, session_id, [
        {"username": "admin", "hash": "pbkdf2_sha256$600000$zzz$FORGED="},
        {"username": "admin", "password": "admin1234"},
    ])

    assert fabricated.json()["credited"] == []
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_crediting_requires_at_least_one_malicious_attempt_in_session(client):
    session_id = start(client)

    response = submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert response.status_code == 200
    assert response.json()["attempted"] is False
    assert response.json()["credited"] == []
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_bigger_dump_adds_higher_tiers_monotonically(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    submit(client, session_id, rows_for("jiwoo"))
    submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }


def test_a_closed_session_refuses_loot(client):
    session_id = start(client)
    fire_exfil(client, session_id)
    client.post_json(f"/api/sessions/{session_id}/close/")

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 409
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_non_loot_wargame_refuses_loot(client):
    with patch("api.views.objectives.solved_keys", return_value=set()):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 400


def test_the_case_id_windows_the_objective_to_the_exfil_case(client):
    session_id = start(client)
    case_id = fire_exfil(client, session_id)

    submit(client, session_id, rows_for("admin"), case_id=case_id)

    objective = Objective.objects.get(session_id=session_id, key="board-auth-user-admin")
    case = Session.objects.get(pk=session_id).cases.get(case_id=case_id)
    assert objective.earliest <= case.ended_at <= objective.latest
    assert objective.earliest <= case.started_at


def test_a_take_with_no_overlapping_case_is_flagged_unattributed(client):
    session_id = start(client)
    old = timezone.now() - timedelta(minutes=30)
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": "33333333-3333-4333-8333-333333333333", "name": "old-attack",
        "malicious": True, "correlation": "marker",
        "started_at": old.isoformat(),
        "ended_at": (old + timedelta(seconds=2)).isoformat(),
    })

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 200
    assert response.json()["attempted"] is True
    assert set(response.json()["unattributed"]) == {
        "board-auth-user-partial", "board-auth-user-admin"
    }
