from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

from api.models import Detection, Objective, Session
from range.ports import Ran

def a_waf_with_an_empty_file(role, segment_id=""):
    return lambda argv, stdin=None, timeout=60.0: Ran(0, "")

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}

EXFIL_CASE = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def session_id(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def _fire_exfil(client, session_id):
    now = timezone.now()
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": EXFIL_CASE, "name": "board-sqli-search", "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })


def _submit(client, session_id, names):
    return client.post_json(f"/api/sessions/{session_id}/loot/", {
        "loot": [{"username": n, "hash": TRUTH[n]} for n in names],
    })


def test_a_closed_session_cannot_be_closed_again(client, session_id):
    first = client.post_json(f"/api/sessions/{session_id}/close/")
    closed_at = Session.objects.get(pk=session_id).ended_at

    with patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=1)):
        again = client.post_json(f"/api/sessions/{session_id}/close/")

    assert first.status_code == 200
    assert again.status_code == 409, (
        f"closing a closed session answered {again.status_code} and moved its end "
        f"a day later, widening the window its alerts are read from into other "
        f"sessions' traffic"
    )
    assert Session.objects.get(pk=session_id).ended_at == closed_at


def test_closing_credits_nothing_new_and_keeps_what_was_submitted(client, session_id):
    _fire_exfil(client, session_id)
    assert _submit(client, session_id, ["admin"]).status_code == 200
    before = {o["key"] for o in client.get(f"/api/sessions/{session_id}/objectives/").json()}

    client.post_json(f"/api/sessions/{session_id}/close/")

    after = {o["key"] for o in client.get(f"/api/sessions/{session_id}/objectives/").json()}
    assert "board-auth-user-admin" in after, "close threw away loot submitted before it"
    assert after == before, (
        "loot is taken only through POST /loot/; a close that credited anything "
        "on its own would score the red team for what it never proved it took"
    )


def test_an_attack_that_was_running_when_the_session_closed_is_still_in_its_window(client, session_id):
    a_case = client.get("/api/wargames/board/cases/").json()[0]["name"]

    def closes_meanwhile(*args, **kwargs):
        client.post_json(f"/api/sessions/{session_id}/close/")

    with patch("api.views.harness.fire", side_effect=closes_meanwhile), patch(
        "api.views._origin_for", return_value=None
    ):
        response = client.post_json(f"/api/sessions/{session_id}/attacks/", {"case": a_case})

    assert response.status_code == 201, response.content
    session = Session.objects.get(pk=session_id)
    recorded = session.cases.get()
    assert session.ended_at >= recorded.ended_at, (
        "the attack reached the target and was recorded, but its session had "
        "closed while it ran, so its evidence fell outside the window it is "
        "scored from and it counted as a miss"
    )


def test_two_loots_at_once_record_an_objective_once(client, session_id):
    from api import views

    _fire_exfil(client, session_id)
    real = views.loot.tiers_fired
    underway = []

    def overtaken(spec, matched_users, truth):
        if not underway:
            underway.append(True)
            _submit(client, session_id, ["admin"])
        return real(spec, matched_users, truth)

    with patch("api.views.loot.tiers_fired", side_effect=overtaken):
        response = _submit(client, session_id, ["admin"])

    assert response.status_code == 200, (
        f"two loot submissions credited the same tier at once, both saw it as "
        f"new, and the second died on the unique constraint: {response.status_code}"
    )
    assert Objective.objects.filter(
        session_id=session_id, key="board-auth-user-admin"
    ).count() == 1


class Rebuilds:
    runner = staticmethod(a_waf_with_an_empty_file)

    def __init__(self, fail=None):
        self.rebuilt = 0
        self.fail = fail

    def rebuild_slot(self):
        self.rebuilt += 1
        if self.fail is not None:
            raise self.fail
        return [("fsl-waf", "srv-1"), ("fsl-wg-board", "srv-2")]


def test_closing_a_session_on_the_cloud_rebuilds_the_slot(client, session_id):
    found = Rebuilds()
    with patch("api.views.substrate", lambda: found):
        response = client.post_json(f"/api/sessions/{session_id}/close/")

    assert response.status_code == 200, response.content
    assert Session.objects.get(pk=session_id).ended_at is not None
    assert found.rebuilt == 1
    assert response.json()["rebuilding"] == [
        {"host": "fsl-waf", "server": "srv-1"},
        {"host": "fsl-wg-board", "server": "srv-2"},
    ]


def test_closing_stamps_ended_at_before_it_rebuilds(client, session_id):
    order = []

    class Recorder:
        runner = staticmethod(a_waf_with_an_empty_file)

        def rebuild_slot(self):
            order.append(Session.objects.get(pk=session_id).ended_at is not None)
            return []

    with patch("api.views.substrate", lambda: Recorder()):
        client.post_json(f"/api/sessions/{session_id}/close/")

    assert order == [True], (
        "the session's ended_at must be stamped before the slot rebuilds, so a "
        "rebuild that wipes the VMs cannot reopen the scoring window onto the "
        "next session's traffic"
    )


def test_a_failed_rebuild_leaves_the_session_closed(client, session_id):
    from range.ports import Drifted

    found = Rebuilds(fail=Drifted("fsl-waf is not standing"))
    with patch("api.views.substrate", lambda: found):
        response = client.post_json(f"/api/sessions/{session_id}/close/")

    assert response.status_code == 200, response.content
    assert Session.objects.get(pk=session_id).ended_at is not None
    assert "fsl-waf" in response.json()["rebuild"]
    assert "rebuilding" not in response.json()


class RebuildsAndConfigures(Rebuilds):
    def configure_slot(self):
        return []


def _silenced(session_id, minutes=60):
    from api.models import Suppression

    return Suppression.objects.create(
        session_id=session_id, sid=9000004, original="alert x",
        expires_at=timezone.now() + timedelta(minutes=minutes),
    )


def test_closing_on_the_cloud_lifts_the_suppressions_the_rebuild_wiped(client, session_id):
    record = _silenced(session_id)

    with patch("api.views.substrate", lambda: RebuildsAndConfigures()), \
            patch("api.views.reset.begin") as began:
        client.post_json(f"/api/sessions/{session_id}/close/")

    record.refresh_from_db()
    assert began.called
    assert record.restored_at == Session.objects.get(pk=session_id).ended_at, (
        "the close rebuilt every slot VM and the reset seeds the baseline rules, "
        "but the suppression stayed on the books, so readiness refused every "
        "new session until it expired"
    )


def _failed_rebuild():
    from range.ports import Drifted

    return RebuildsAndConfigures(fail=Drifted("fsl-waf is not standing"))


@pytest.mark.parametrize("found", [_failed_rebuild, None], ids=["cloud-rebuild-failed", "compose"])
def test_a_close_that_rebuilt_nothing_keeps_the_suppression_on_the_books(client, session_id, found):
    record = _silenced(session_id)

    if found is None:
        client.post_json(f"/api/sessions/{session_id}/close/")
    else:
        adapter = found()
        with patch("api.views.substrate", lambda: adapter), patch("api.views.reset.begin"):
            client.post_json(f"/api/sessions/{session_id}/close/")

    record.refresh_from_db()
    assert record.restored_at is None, (
        "nothing was rebuilt, so the sensor still runs with the rule commented out"
    )


def test_closing_deletes_only_sessions_closed_longer_ago_than_the_retention_with_their_detections(client, session_id):
    now = timezone.now()
    kept_for = timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)
    expired = Session.objects.create(scenario="board", baseline=[], ended_at=now - kept_for - timedelta(minutes=1))
    recent = Session.objects.create(scenario="board", baseline=[], ended_at=now - kept_for + timedelta(minutes=1))
    for session in (expired, recent):
        Detection.objects.create(session=session, detection_id="d", source="suricata", signature="s", timestamp=now)

    assert client.post_json(f"/api/sessions/{session_id}/close/").status_code == 200

    assert set(Session.objects.values_list("pk", flat=True)) == {session_id, recent.pk}, (
        "the store grew to 6 GB of closed sessions; one closed past FSL_RETAIN_CLOSED_MINUTES goes, "
        "while the one just closed and one still inside the retention must stay for their score and debrief"
    )
    assert list(Detection.objects.values_list("session", flat=True)) == [recent.pk]


def test_an_expired_session_s_detections_go_in_transactions_no_larger_than_the_batch(monkeypatch):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from api import retention

    now = timezone.now()
    expired = Session.objects.create(scenario="board", baseline=[], ended_at=now - timedelta(days=1))
    Detection.objects.bulk_create(
        Detection(session=expired, detection_id=f"d{n}", source="suricata", signature="s", timestamp=now)
        for n in range(5))
    monkeypatch.setattr(retention, "ROWS_PER_TRANSACTION", 2)

    with CaptureQueriesContext(connection) as ran:
        assert retention.prune(now) == 1

    deletes = [query["sql"] for query in ran
               if query["sql"].startswith('DELETE FROM "api_detection" WHERE "api_detection"."id" IN')]
    assert len(deletes) == 3 and not Detection.objects.exists(), (
        "one session's 1.9 M-row cascade in a single transaction held the store's write lock past the "
        "30 s busy timeout, and the scenario engine's tick failed with 'database is locked'"
    )
