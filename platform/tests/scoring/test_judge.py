from datetime import datetime, timedelta, timezone

import pytest

from scoring import score as service
from scoring.models import Verdict
from tests import rounds

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)
WAIT = timedelta(seconds=30)
SQLI = "board-sqli-search"
XSS = "board-xss-comment"
BENIGN = "board-normal-search"


def a_round():
    return rounds.opened(rounds.problem(), started=AT - timedelta(minutes=10))


def judged(found, actions, detections, now, running=frozenset()):
    return [(row.action, row.verdict, row.alerts, row.corroborated)
            for row in service.judge(found, actions, detections, set(running), now, WAIT)]


def test_a_case_with_a_matching_alert_is_judged_at_the_first_read_after_it_ends():
    found = a_round()
    actions = [rounds.case(SQLI, AT, malicious=True, expect="sql injection")]
    alerts = [rounds.detection("d1", AT, marker=SQLI, signature="ET WEB SQL Injection")]

    assert judged(found, actions, alerts, AT + timedelta(seconds=2)) == [(SQLI, "tp", 1, True)]


def test_a_case_without_an_alert_waits_out_the_alert_delay_before_it_is_a_miss():
    found = a_round()
    actions = [rounds.case(SQLI, AT, malicious=True, expect="sql injection"),
               rounds.case(BENIGN, AT, malicious=False)]

    assert judged(found, actions, [], AT + timedelta(seconds=10)) == []
    assert judged(found, actions, [], AT + timedelta(seconds=32)) == [(SQLI, "fn", 0, False), (BENIGN, "tn", 0, None)]


def test_an_alert_on_benign_traffic_is_a_false_positive_at_once():
    found = a_round()
    actions = [rounds.case(BENIGN, AT, malicious=False)]
    alerts = [rounds.detection("d1", AT, marker=BENIGN, signature="ET WEB SQL Injection")]

    assert judged(found, actions, alerts, AT + timedelta(seconds=2)) == [(BENIGN, "fp", 1, None)]


def test_one_case_is_judged_once_however_many_alerts_follow_or_reads_run():
    found = a_round()
    actions = [rounds.case(SQLI, AT, malicious=True, expect="sql injection")]
    first = [rounds.detection("d1", AT, marker=SQLI, signature="ET WEB SQL Injection")]
    more = first + [rounds.detection(f"d{n}", AT, marker=SQLI, signature="ET WEB SQL Injection") for n in range(2, 9)]

    assert judged(found, actions, first, AT + timedelta(seconds=2)) == [(SQLI, "tp", 1, True)]
    assert judged(found, actions, more, AT + timedelta(minutes=5)) == []
    assert Verdict.objects.filter(round=found).count() == 1


def test_a_tool_case_still_running_is_not_judged_until_it_stops_or_the_round_ends():
    found = a_round()
    actions = [rounds.case(SQLI, AT, malicious=True, expect="sql injection")]
    alerts = [rounds.detection("d1", AT, marker=SQLI, signature="ET SCAN Sqlmap")]

    assert judged(found, actions, alerts, AT + timedelta(minutes=5), running={SQLI}) == []
    found.ended = AT + timedelta(minutes=6)
    assert judged(found, actions, alerts, AT + timedelta(minutes=6), running={SQLI}) == [(SQLI, "tp", 1, False)]


def test_the_round_s_end_judges_every_case_left_and_ignores_what_came_after_it():
    found = a_round()
    found.ended = AT + timedelta(seconds=5)
    actions = [rounds.case(SQLI, AT, malicious=True, expect="sql injection"),
               rounds.case(XSS, AT + timedelta(seconds=9), malicious=True, expect="xss")]
    late = [rounds.detection("d1", AT + timedelta(seconds=8), marker=SQLI, signature="ET WEB SQL Injection")]

    assert judged(found, actions, late, AT + timedelta(seconds=10)) == [(SQLI, "fn", 0, False)]


def test_free_actions_are_never_judged():
    found = a_round()
    actions = [rounds.action("free-1", AT)]
    alerts = [rounds.detection("d1", AT, marker="free-1", signature="ET WEB SQL Injection")]

    assert judged(found, actions, alerts, AT + timedelta(minutes=5)) == []
