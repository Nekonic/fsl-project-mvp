import threading
import time
from unittest.mock import patch

import pytest

from range.ports import Ran
from rules import suricata

pytestmark = pytest.mark.django_db(transaction=True)

TWO_RULES = (
    'alert http any any -> any any (msg:"one"; sid:9000901; rev:1;)\n'
    'alert http any any -> any any (msg:"two"; sid:9000902; rev:1;)\n'
)


class SlowSensor:
    def __init__(self, rules):
        self.rules = rules

    def runner(self, role, segment_id=""):
        return self

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[:1] == ["cat"]:
            seen = self.rules
            time.sleep(0.3)
            return Ran(0, seen)
        if argv[:2] == ["sh", "-c"] and suricata.RULE_PATH in argv[-1]:
            self.rules = stdin
        if "reload-rules" in argv:
            return Ran(0, '{"message":"done","return":"OK"}')
        return Ran(0, "")


def test_two_suppressions_at_once_both_take_effect(client):
    sensor = SlowSensor(TWO_RULES)

    def silence(sid):
        client.post_json("/api/rules/suppressions/", {"sid": sid, "minutes": 5})

    with patch("api.views.substrate", return_value=sensor):
        both = [threading.Thread(target=silence, args=(sid,)) for sid in (9000901, 9000902)]
        for thread in both:
            thread.start()
        for thread in both:
            thread.join()

    live = [line for line in sensor.rules.splitlines() if line.startswith("alert")]
    assert live == [], (
        f"two suppressions read the same rule file, each wrote back its own "
        f"edit, and the second erased the first: {live} is still live while "
        f"the suppression list says it is silenced"
    )


def tick_while_a_rule_change_runs(client, change_takes):
    from api import views

    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    holding, finished = threading.Event(), threading.Event()

    def validating():
        with views.RULE_CHANGES:
            holding.set()
            finished.wait(change_takes)

    change = threading.Thread(target=validating)
    change.start()
    holding.wait()
    started = time.monotonic()
    with patch("api.views.elastic.fetch", return_value=([], None)):
        response = client.post_json(f"/api/sessions/{session_id}/ingest/")
    took = time.monotonic() - started
    finished.set()
    change.join()
    return response, took


def test_a_tick_with_nothing_to_lift_does_not_wait_behind_a_rule_change(client):
    response, took = tick_while_a_rule_change_runs(client, change_takes=2.0)

    assert response.status_code == 200, response.content
    assert took < 1.0, (
        f"the tick took {took:.2f}s: it waited for a validate or apply to "
        f"finish although no suppression was due, so every blue window's "
        f"alert feed stopped for the length of a suricata -T run"
    )


def test_a_tick_with_a_lift_due_still_waits_its_turn(client):
    from datetime import timedelta

    from django.utils import timezone

    from api.models import Suppression
    from suppress import MARKER
    from tests.test_ingest_boundaries import Sensor

    Suppression.objects.create(
        sid=9000901, original=TWO_RULES.splitlines()[0], reason="",
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    sensor = Sensor(f"{MARKER} until t\n#{TWO_RULES}")

    with patch("api.views.substrate", return_value=sensor):
        response, took = tick_while_a_rule_change_runs(client, change_takes=0.5)

    assert response.status_code == 200, response.content
    assert took >= 0.4, (
        f"the lift ran after {took:.2f}s, beside a rule change still in "
        f"progress, and one of the two writes erased the other"
    )
    assert [r["ok"] for r in response.json()["restored"]] == [True]
