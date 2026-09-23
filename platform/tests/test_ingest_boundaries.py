import threading
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Detection, Session, Suppression
from range.ports import Ran
from rules import suricata

MARKER = "11111111-1111-4111-8111-111111111111"
RULE = 'alert http any any -> any any (msg:"one"; sid:9000901; rev:1;)\n'


def alert(doc_id, when):
    return (doc_id, {
        "fsl_source": "suricata", "event_type": "alert",
        "timestamp": when.isoformat(), "src_ip": "5.188.10.5",
        "alert": {"signature": "SQLi", "severity": 1},
        "http": {"request_headers": [{"name": "X-FSL-Case", "value": MARKER}]},
    })


class Sensor:
    def __init__(self, rules):
        self.rules = rules

    def runner(self, role, segment_id=""):
        return self

    def describe(self):
        from range.ports import Shape
        return Shape(segments=(), sensors=())

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[:1] == ["cat"]:
            return Ran(0, self.rules)
        if argv[:2] == ["sh", "-c"] and suricata.RULE_PATH in argv[-1]:
            self.rules = stdin
        return Ran(0, "")


@pytest.mark.django_db
def test_an_old_alert_shipped_again_is_not_evidence_of_this_session(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    now = timezone.now()
    reshipped = alert("old", now - timedelta(days=2))
    fresh = alert("new", now)

    with patch("api.views.elastic.fetch", return_value=([reshipped, fresh], None)):
        answer = client.post_json(f"/api/sessions/{session_id}/ingest/").json()

    assert list(Detection.objects.filter(session_id=session_id).values_list("detection_id", flat=True)) == ["new"], (
        "a VM restart makes Filebeat ship old log lines again with a fresh "
        "@timestamp, and the session took two-day-old alerts as its own"
    )
    assert answer["stale"] == 1


@pytest.mark.django_db(transaction=True)
def test_two_ingests_at_once_neither_fails_nor_doubles(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    documents = [alert(f"d{n}", timezone.now()) for n in range(5)]

    def slow_fetch(*args, **kwargs):
        time.sleep(0.3)
        return documents, None

    answers = []

    def ingest():
        answers.append(client.post_json(f"/api/sessions/{session_id}/ingest/").status_code)

    with patch("api.views.elastic.fetch", side_effect=slow_fetch):
        both = [threading.Thread(target=ingest) for _ in range(2)]
        for thread in both:
            thread.start()
        for thread in both:
            thread.join()

    assert answers == [200, 200], (
        f"two console ticks overlapped and one ingest died on the unique "
        f"constraint: {answers}"
    )
    assert Detection.objects.filter(session_id=session_id).count() == 5


@pytest.mark.django_db
def test_a_suppression_past_its_time_is_lifted_by_the_tick_the_console_runs(client):
    sensor = Sensor("# " + RULE)
    Suppression.objects.create(
        sid=9000901, original=RULE, reason="",
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    with patch("api.views.substrate", return_value=sensor), patch(
        "api.views.elastic.fetch", return_value=([], None)
    ):
        answer = client.post_json(f"/api/sessions/{session_id}/ingest/").json()

    assert RULE in sensor.rules, (
        "a suppression expired only when someone opened the suppression list; "
        "an open console never did, so a sixty-minute silence lasted until "
        "someone looked"
    )
    assert [r["sid"] for r in answer["restored"]] == [9000901]


@pytest.mark.django_db
def test_rules_edited_from_a_stale_copy_are_refused(client):
    sensor = Sensor(RULE)

    with patch("api.views.substrate", return_value=sensor):
        loaded = client.get("/api/rules/").json()
        sensor.rules = "# " + RULE
        stale = client.post_json("/api/rules/apply/", {"content": loaded["content"], "base": loaded["version"]})

    assert stale.status_code == 409, (
        "the editor was loaded before a suppression and applied after it, "
        "writing the silenced rule back live while the list still said it was "
        "suppressed"
    )
    assert sensor.rules == "# " + RULE


@pytest.mark.django_db
def test_rules_applied_from_the_current_copy_go_through(client):
    sensor = Sensor(RULE)

    with patch("api.views.substrate", return_value=sensor):
        loaded = client.get("/api/rules/").json()
        applied = client.post_json("/api/rules/apply/", {"content": RULE + RULE.replace("9000901", "9000902"), "base": loaded["version"]})

    assert applied.status_code == 200, applied.content
