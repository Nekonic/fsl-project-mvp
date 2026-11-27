from datetime import datetime, timedelta, timezone

import pytest

from domain.types import DetectionRecord
from telemetry import events as log
from telemetry.access import OriginRequest
from telemetry.models import Detection
from tests import rounds
from training.attack.actions import origin_record
from training.models import BotNote, BotRun, Player
from training.round import debrief

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
ORIGIN = "5.188.10.10"


BOT_NOTES = (
    ("call", "python -m bots.cli attack_send --json '{\"method\":\"GET\",\"path\":\"/\"}'"),
    ("text", "Meanwhile, look at the target."),
    ("refused", "model_refusal_fallback claude-opus-5-5 -> claude-opus-4-8 [cyber]: safeguards flagged this session"),
    ("refused", "pace_limited POST /api/rounds/480/attack/requests/ {\"retry_after_s\": 0.3}"),
    ("text", "**지금까지의 경과**\n## 다음 단계\n`sort` 파라미터를 다시 본다"),
    ("result", "정렬 파라미터로 __계정 목록__을 확인했다"),
)
SHOWN_NOTES = [("text", "지금까지의 경과\n다음 단계\nsort 파라미터를 다시 본다"),
               ("result", "정렬 파라미터로 계정 목록을 확인했다")]


def bot_notes_of(found):
    run = BotRun.objects.create(player=Player.objects.create(round=found, side="attack", client="bot", step="3"),
                                model="claude-haiku-5-5")
    BotNote.objects.bulk_create([BotNote(run=run, at=AT + timedelta(seconds=n), kind=kind, text=text)
                                 for n, (kind, text) in enumerate(BOT_NOTES)])


def test_the_learner_sees_only_the_bot_s_korean_notes_without_markdown_and_none_of_its_commands_or_notices():
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30), phase="ended",
                          ended=AT + timedelta(minutes=10))
    bot_notes_of(found)

    assert [(row["note"], row["text"]) for row in debrief.note_rows(found)] == SHOWN_NOTES


def test_a_debrief_kept_before_notes_were_filtered_is_shown_filtered():
    kept = {"round": 1, "timeline": [{"lane": "attack", "kind": "bot_note", "at": AT.isoformat(), "note": kind,
                                      "text": text} for kind, text in BOT_NOTES]
                                    + [{"lane": "attack", "kind": "tool.started", "at": AT.isoformat(), "tool": "sqlmap"}]}

    shown = debrief.cleaned(kept)

    assert [(row.get("note"), row.get("text")) for row in shown["timeline"]] == SHOWN_NOTES + [(None, None)]


def test_the_attack_lane_carries_tunnelled_requests_grouped_by_origin_with_the_score_s_alert_count(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    tunnelled = tuple(origin_record(OriginRequest(id=doc_id, at=AT + timedelta(seconds=offset), ip=ORIGIN,
                                                  method="GET", host="board.com", path="/search/"))
                      for doc_id, offset in (("a1", 0), ("a2", 30)))
    between = rounds.detection("d2", AT + timedelta(seconds=15), marker=None, src_ip=ORIGIN)
    monkeypatch.setattr(debrief.lifecycle.attack, "origin_records", lambda round_: tunnelled)
    monkeypatch.setattr(debrief.alert_feed, "detections",
                        lambda round_: [rounds.detection("d1", AT + timedelta(seconds=31), marker=None, src_ip=ORIGIN), between])

    composed = debrief.compose(found)

    rows = [row for row in composed["timeline"] if row["kind"] == "free_actions"]
    assert rows == [{"lane": "attack", "kind": "free_actions", "at": AT.isoformat(), "origin": ORIGIN, "count": 2,
                     "until": (AT + timedelta(seconds=30)).isoformat(), "alerts": 1}]
    assert [origin["alerts"] for origin in composed["score"]["free_actions"]["by_origin"]] == [1]


def test_the_debrief_reads_the_round_s_alerts_and_actions_once_however_many_parts_use_them(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30), phase="ended",
                          ended=AT + timedelta(minutes=10))
    reads = []
    monkeypatch.setattr(debrief.alert_feed, "detections", lambda round_: reads.append("alerts") or [])
    monkeypatch.setattr(debrief.lifecycle, "actions", lambda round_: reads.append("actions") or ())

    debrief.compose(found)

    assert sorted(reads) == ["actions", "alerts"]


def test_the_alert_records_carry_every_field_the_score_reads_but_not_the_raw_document():
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    Detection.objects.create(round=found, detection_id="d1", engine="waf", rule="942100", signature="SQL Injection",
                             timestamp=AT, src_ip=ORIGIN, marker="m1", uri="/search/", blocked=True,
                             raw={"details": {"ruleId": "942100"}})

    assert debrief.alert_feed.detections(found) == (DetectionRecord(
        detection_id="d1", timestamp=AT, src_ip=ORIGIN, marker="m1", engine="waf", rule="942100",
        signature="SQL Injection", uri="/search/", blocked=True),)


def test_alerts_group_by_rule_so_one_deny_rule_is_one_row_however_many_requests_it_refused(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    refusals = [DetectionRecord(detection_id=f"a{n}", timestamp=AT + timedelta(seconds=n), src_ip=ORIGIN, marker=None,
                                engine="waf", rule="403", signature=f"403 GET /p{n} HTTP/1.1", blocked=True)
                for n in range(3)]

    rows = debrief.alert_rows(refusals)

    assert rows == [{"lane": "defence", "kind": "alerts", "at": AT.isoformat(), "engine": "waf", "rule": "403",
                     "signature": "403 GET /p0 HTTP/1.1", "count": 3, "rules": 1,
                     "until": (AT + timedelta(seconds=2)).isoformat()}]


def test_a_case_s_alerts_are_one_line_at_its_first_alert_naming_its_most_frequent_rule_and_refusals_stay_apart():
    def alert(n: int, rule: str, signature: str, marker: str | None = "case-1") -> DetectionRecord:
        return DetectionRecord(detection_id=f"a{n}", timestamp=AT + timedelta(seconds=n), src_ip=ORIGIN, marker=marker,
                               engine="waf", rule=rule, signature=signature, blocked=True)
    seen = [alert(0, "942100", "SQL Injection"), alert(1, "949110", "Anomaly Score"), alert(2, "949110", "Anomaly Score"),
            alert(3, "403", "403 GET /posts/?sort=1 HTTP/1.1"), alert(4, "942100", "SQL Injection", marker=None),
            alert(5, "949110", "Anomaly Score", marker="unknown")]

    rows = debrief.alert_rows(seen, frozenset({"case-1"}))

    assert [(row["at"], row["rule"], row["count"], row["rules"]) for row in rows] == [
        (AT.isoformat(), "949110", 3, 2), ((AT + timedelta(seconds=3)).isoformat(), "403", 1, 1),
        ((AT + timedelta(seconds=4)).isoformat(), "942100", 1, 1),
        ((AT + timedelta(seconds=5)).isoformat(), "949110", 1, 1)]


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
    monkeypatch.setattr(debrief.lifecycle.attack, "running", lambda round_: set())
    monkeypatch.setattr(debrief.lifecycle.attack, "origin_records", lambda round_: ())
    monkeypatch.setattr(debrief.alert_feed, "detections", lambda round_: [])
    title = debrief.lifecycle.case_titles(found)["board-sqli-search"]

    debrief.lifecycle.judge(found, at=end + timedelta(hours=1))
    composed = debrief.compose(found)

    [judged] = [event["body"] for event in debrief.events_of(found) if event["kind"] == "case.judged"]
    assert title != "board-sqli-search" and judged["title"] == title
    assert [line["title"] for line in composed["score"]["outcomes"]["per_case"]] == [title]
    assert [row["title"] for row in composed["timeline"] if row.get("case")] == [title]
