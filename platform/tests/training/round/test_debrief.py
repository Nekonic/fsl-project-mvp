from datetime import datetime, timedelta, timezone

import pytest

from domain.types import DetectionRecord
from telemetry import events as log
from telemetry.access import OriginRequest
from tests import rounds
from training.attack.actions import origin_record
from training.round import debrief

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
ORIGIN = "5.188.10.10"


def test_the_attack_lane_carries_tunnelled_requests_grouped_by_origin_with_the_score_s_alert_count(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    tunnelled = tuple(origin_record(OriginRequest(id=doc_id, at=AT + timedelta(seconds=offset), ip=ORIGIN,
                                                  method="GET", host="board.com", path="/search/"))
                      for doc_id, offset in (("a1", 0), ("a2", 30)))
    between = rounds.detection("d2", AT + timedelta(seconds=15), marker=None, src_ip=ORIGIN)
    monkeypatch.setattr(debrief.attack, "origin_records", lambda round_: tunnelled)
    monkeypatch.setattr(debrief.alert_feed, "detections",
                        lambda round_: [rounds.detection("d1", AT + timedelta(seconds=31), marker=None, src_ip=ORIGIN), between])

    composed = debrief.compose(found)

    rows = [row for row in composed["timeline"] if row["kind"] == "free_actions"]
    assert rows == [{"lane": "attack", "kind": "free_actions", "at": AT.isoformat(), "origin": ORIGIN, "count": 2,
                     "until": (AT + timedelta(seconds=30)).isoformat(), "alerts": 1}]
    assert [origin["alerts"] for origin in composed["score"]["free_actions"]["by_origin"]] == [1]


def test_alerts_group_by_rule_so_one_deny_rule_is_one_row_however_many_requests_it_refused(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    refusals = [DetectionRecord(detection_id=f"a{n}", timestamp=AT + timedelta(seconds=n), src_ip=ORIGIN, marker=None,
                                engine="waf", rule="403", signature=f"403 GET /p{n} HTTP/1.1", blocked=True)
                for n in range(3)]
    monkeypatch.setattr(debrief.alert_feed, "detections", lambda round_: refusals)

    rows = debrief.alert_rows(found)

    assert rows == [{"lane": "defence", "kind": "alerts", "at": AT.isoformat(), "engine": "waf", "rule": "403",
                     "signature": "403 GET /p0 HTTP/1.1", "count": 3,
                     "until": (AT + timedelta(seconds=2)).isoformat()}]


def test_judged_cases_sit_at_their_firing_time_and_repeated_benign_verdicts_are_one_row(monkeypatch):
    end = AT + timedelta(minutes=10)
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30), phase="ended", ended=end)
    fired = [rounds.case("attack-1", AT, malicious=True),
             rounds.case("benign-1", AT + timedelta(seconds=5), malicious=False),
             rounds.case("benign-2", AT + timedelta(seconds=9), malicious=False)]
    monkeypatch.setattr(debrief.lifecycle, "logged_actions", lambda round_: tuple(fired))
    for action, case, verdict in (("attack-1", "board-sqli-search", "tp"), ("benign-1", "board-normal-home", "tn"),
                                  ("benign-2", "board-normal-home", "tn"), ("gone", "board-sqli-union", "fn")):
        log.append(found.pk, "case.judged", {"action": action, "case": case, "title": case, "verdict": verdict, "alerts": 0,
                                             "corroborated": None})

    rows = sorted((row["case"], row["at"], row.get("count")) for row in debrief.event_rows(found))

    assert rows == [("board-normal-home", (AT + timedelta(seconds=5)).isoformat(), 2),
                    ("board-sqli-search", AT.isoformat(), None),
                    ("board-sqli-union", end.isoformat(), None)]


def test_every_case_line_the_console_shows_carries_the_case_s_korean_title(monkeypatch):
    end = AT + timedelta(minutes=10)
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30), phase="ended", ended=end)
    fired = (rounds.case("board-sqli-search", AT, malicious=True),)
    monkeypatch.setattr(debrief.lifecycle, "logged_actions", lambda round_: fired)
    monkeypatch.setattr(debrief.lifecycle, "actions", lambda round_: fired)
    monkeypatch.setattr(debrief.attack, "running", lambda round_: set())
    monkeypatch.setattr(debrief.attack, "origin_records", lambda round_: ())
    monkeypatch.setattr(debrief.alert_feed, "detections", lambda round_: [])
    title = debrief.lifecycle.case_titles(found)["board-sqli-search"]

    debrief.lifecycle.judge(found, at=end + timedelta(hours=1))
    composed = debrief.compose(found)

    [judged] = [event["body"] for event in debrief.events_of(found) if event["kind"] == "case.judged"]
    assert title != "board-sqli-search" and judged["title"] == title
    assert [line["title"] for line in composed["score"]["outcomes"]["per_case"]] == [title]
    assert [row["title"] for row in composed["timeline"] if row.get("case")] == [title]
