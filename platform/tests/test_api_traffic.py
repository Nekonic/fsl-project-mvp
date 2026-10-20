import json
import re
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Case, CustomerRequest, Detection, Session
from range.ports import Node, Ran, Segment

pytestmark = pytest.mark.django_db

SEGMENTS = (
    Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24", network="fsl_edge",
            nodes=(Node("fsl-kali", "5.188.10.5"), Node("fsl-waf", "5.188.10.9"))),
    Segment(id="us", name="Internet", origin="United States", subnet="73.0.0.0/24", network="fsl_edge-us",
            nodes=(Node("fsl-kali", "73.0.0.5"), Node("fsl-kali", "73.0.0.6"), Node("fsl-waf", "73.0.0.9"))),
    Segment(id="hk", name="Internet", origin="Hong Kong", subnet="103.152.220.0/24", network="fsl_edge-hk",
            nodes=(Node("fsl-kali", "103.152.220.5"), Node("fsl-kali", "103.152.220.6"), Node("fsl-waf", "103.152.220.9"))),
)

class Box:
    def __init__(self):
        self.records = ""
        self.running = False
        self.program = None
        self.plans = []
        self.stopped = 0

    def add(self, *records):
        self.records += "".join(json.dumps(record) + "\n" for record in records)

    def __call__(self, argv, stdin=None, timeout=60.0):
        script = argv[-1]
        if "route get" in script:
            return Ran(0, "5.188.10.1 dev eth0 src 5.188.10.5 uid 0\n")
        if "fsl.records=" in script:
            offset = int(re.search(r"tail -c \+(\d+)", script)[1]) - 1
            limit = int(re.search(r"head -c (\d+)", script)[1])
            return Ran(0, "fsl.records=\n" + self.records[offset:offset + limit] + "\n=fsl.records\n")
        if "users.py.new" in script:
            self.program = stdin
            return Ran(0, "")
        if "plan.json.new" in script:
            self.plans.append(json.loads(stdin))
            started, self.running = not self.running, True
            return Ran(0, "fsl.customers=started\n" if started else "fsl.customers=changed\n")
        if "kill" in script and "rm -f" in script:
            self.running = False
            self.stopped += 1
        return Ran(0, "")

class Range:
    def __init__(self, box):
        self.box = box
        self.asked = []

    def segments(self):
        return SEGMENTS

    def users_box(self, segment_ids, image):
        self.asked.append(list(segment_ids))
        return self.box

    def runner(self, role, segment_id=""):
        return self.box

@pytest.fixture
def box():
    return Box()

@pytest.fixture
def the_range(box):
    found = Range(box)
    with patch("api.views._range", lambda session=None, adapter=None: found):
        yield found

@pytest.fixture
def session(db):
    return Session.objects.create(scenario="board", baseline=[])

def put(client, session, body):
    return client.put(f"/api/sessions/{session.pk}/traffic/", json.dumps(body), content_type="application/json")

def record(status=200, action="home", **given):
    return {"marker": str(uuid.uuid4()), "action": action, "step": "home", "user": "u01", "origin": "us",
            "source_ip": "73.0.0.7", "method": "GET", "path": "/", "status": status, "refused_by": "",
            "sent_at": timezone.now().isoformat(), "elapsed_ms": 12, **given}

def test_put_starts_the_customers_from_origins_other_than_the_attackers(client, session, the_range, box):
    started = put(client, session, {})

    assert started.status_code == 200, started.content
    assert started.json()["running"] is True
    plan = box.plans[-1]
    assert {user["origin"] for user in plan["users"]} <= {"us", "hk"}, "a customer came from the attacker's origin"
    assert the_range.asked[-1] == sorted({user["origin"] for user in plan["users"]})

def test_get_reads_every_record_once_and_counts_blocked_customers(client, session, the_range, box):
    put(client, session, {})
    box.add(record(), record(), record(status=403, action="search-unusual"))
    box.records += '{"marker": "half'

    first = client.get(f"/api/sessions/{session.pk}/traffic/").json()
    box.records = box.records.removesuffix('{"marker": "half')
    box.add(record(status=0), record(status=403, refused_by="app", action="comment"))
    second = client.get(f"/api/sessions/{session.pk}/traffic/").json()

    assert (first["sent"], first["blocked"]) == (3, 1)
    assert (second["sent"], second["blocked"], second["unanswered"], second["other"]) == (5, 1, 1, 1), (
        "a CSRF refusal by the board is not a block by the defence"
    )
    assert second["by_action"]["search-unusual"] == {"sent": 1, "blocked": 1}
    assert CustomerRequest.objects.filter(session=session).count() == 5

def test_closing_the_session_stops_the_customers(client, session, the_range, box):
    put(client, session, {})
    box.add(record())

    closed = client.post_json(f"/api/sessions/{session.pk}/close/")
    after = client.get(f"/api/sessions/{session.pk}/traffic/").json()

    assert closed.status_code == 200
    assert box.running is False, "the customers kept sending after the session closed"
    assert after["running"] is False and after["sent"] == 1 and after["stopped_at"]
    assert put(client, session, {}).status_code == 409

def test_a_close_with_the_box_unreachable_still_closes_and_says_why(client, session, the_range, box):
    from range.ports import RangeUnavailable
    put(client, session, {})

    def gone(argv, stdin=None, timeout=60.0):
        raise RangeUnavailable("fsl-kali at 10.31.0.180 never reported the command finishing")

    the_range.box = gone
    closed = client.post_json(f"/api/sessions/{session.pk}/close/")
    state = Session.objects.get(pk=session.pk).traffic

    assert closed.status_code == 200
    assert state["running"] is False and "10.31.0.180" in state["error"]

def _detection(session, marker, src_ip, at, detection_id=None):
    return Detection.objects.create(
        session=session, detection_id=detection_id or str(uuid.uuid4()), source="modsecurity",
        signature="Inbound Anomaly Score Exceeded", timestamp=at, src_ip=src_ip, marker=marker,
    )

def _customer(session, status, marker=None, source_ip="73.0.0.7"):
    return CustomerRequest.objects.create(
        session=session, marker=marker or str(uuid.uuid4()), action="search-unusual", step="search", user="u03",
        origin="us", source_ip=source_ip, method="GET", path="/search/?q=%3Cb%3E", status=status,
        sent_at=timezone.now(),
    )

def test_the_second_score_counts_blocked_customer_requests_beside_the_cases(client, session):
    now = timezone.now()
    sqlmap = Case.objects.create(
        session=session, case_id=str(uuid.uuid4()), name="board-sqli-orderby-sqlmap", malicious=True,
        correlation="marker", source_ip="5.188.10.5", started_at=now, ended_at=now + timedelta(seconds=60),
    )
    blocked = _customer(session, 403)
    _customer(session, 200)
    _customer(session, 200)
    _detection(session, sqlmap.case_id, "5.188.10.5", now + timedelta(seconds=5))
    _detection(session, blocked.marker, "73.0.0.7", now + timedelta(seconds=6))
    _detection(session, None, "9.9.9.9", now + timedelta(seconds=7))

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["customers"]["sent"] == 3 and score["customers"]["blocked"] == 1
    assert score["customers"]["alerted"] == 1 and score["customers"]["blocked_actions"] == {"search-unusual": 1}
    assert [(case["name"], len(case["detection_ids"])) for case in score["per_case"]] == [
        ("board-sqli-orderby-sqlmap", 1)], "a customer's alert was counted against a case, or a case per request"
    assert score["unattributed"] == 1, "a customer's alert is attributed to the customer, not left unattributed"
    assert (score["tp"], score["fp"]) == (1, 0)

def test_window_correlation_does_not_hand_a_customers_alert_to_a_concurrent_attack(client, session):
    now = timezone.now()
    Case.objects.create(
        session=session, case_id=str(uuid.uuid4()), name="board-sqli-orderby-sqlmap", malicious=True,
        correlation="window", source_ip="5.188.10.5", started_at=now, ended_at=now + timedelta(seconds=60),
    )
    customer = _customer(session, 403)
    _detection(session, customer.marker, "73.0.0.7", now + timedelta(seconds=10))

    score = client.get(f"/api/sessions/{session.pk}/score/?correlation=window").json()

    assert score["per_case"][0]["detected"] is False
    assert score["customers"]["blocked"] == 1
