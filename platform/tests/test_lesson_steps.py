import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import kibana
import wargames
from api import site, views
from api.models import Case, Detection, Objective, Session
from console import strings

pytestmark = pytest.mark.django_db

TRUTH = json.loads((Path(__file__).resolve().parent / "fixtures" / "board-auth-users.json").read_text())
KALI, CUSTOMER, WAF, BOARD = "5.188.10.10", "175.192.0.10", "10.30.0.177", "10.30.0.184"

def board(**fields):
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), **fields)

def taught(lesson_id, **fields):
    return board(guidance=True, lesson=lesson_id, defense=wargames.lesson_defense("board", lesson_id), **fields)

def worked(scenario_id):
    return board(guidance=True, lesson=scenario_id, course_scenario=scenario_id,
                 defense=wargames.scenario_run(scenario_id)["defense"])

def step(client, session, step_id, tail="", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def check(client, session, step_id, body=None):
    return step(client, session, step_id, "check/", body)

def withheld_texts(prefix):
    return {encoded(text) for table in strings.withheld().values() for key, text in table.items()
            if key.startswith(f"{prefix}.")}

def encoded(text):
    return json.dumps(text, ensure_ascii=False)[1:-1]

def hint(client, session, step_id):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/hints/", {"step": step_id, "level": "hint"}).json()

def test_no_answer_text_for_an_unreached_step_is_in_the_session_payload(client):
    session = worked("3.1")

    payload = json.dumps(client.get(f"/api/sessions/{session.pk}/").json(), ensure_ascii=False)

    assert "sid:9000102" not in payload and "pcre:" not in payload
    assert not [text for text in withheld_texts("scenario.fixrule") if text in payload]

@pytest.mark.parametrize("wargame_id, lesson_id", [
    *[(wargame_id, lesson_id) for wargame_id in wargames.WARGAMES for lesson_id in wargames.taught_ids(wargame_id)],
    *[(wargame_id, one["id"]) for wargame_id in wargames.WARGAMES for one in wargames.stepped_scenarios(wargame_id)],
])
def test_no_foundation_or_worked_scenario_sends_a_step_command_or_a_withheld_text_before_the_step_is_reached(
        client, wargame_id, lesson_id):
    taught_now = wargames.lesson(wargame_id, lesson_id=lesson_id)
    course = "" if lesson_id in wargames.taught_ids(wargame_id) else lesson_id
    session = Session.objects.create(scenario=wargame_id, baseline={}, guidance=True, lesson=lesson_id,
                                     course_scenario=course)

    payload = json.dumps(client.get(f"/api/sessions/{session.pk}/").json(), ensure_ascii=False)

    assert not [step["id"] for step in taught_now.get("steps", [])
                if step.get("command") and encoded(step["command"]) in payload]
    assert not [text for text in withheld_texts(taught_now["text"]) if text in payload]

def test_a_step_s_command_arrives_once_the_step_is_reached(client):
    session = taught("f6")
    command = next(shown["command"] for shown in wargames.lesson("board", lesson_id="f6")["steps"]
                   if shown["id"] == "excluded")

    reached = step(client, session, "excluded", body={"state": "reached"}).json()
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert command == f"grep -n ruleRemove {settings.FSL_WAF.rules}"
    assert reached["progress"]["excluded"]["command"] == command
    assert shown["excluded"]["command"] == command
    assert "command" not in shown["dump"] and "command" not in reached["progress"].get("dump", {})

def test_the_f5_address_step_gives_the_exact_address_in_a_command_box_once_the_step_is_reached(client):
    session = taught("f5")

    step(client, session, "error", body={"state": "reached"})
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert shown["error"]["command"] == "http://board.com/?sort=posts_post.id)"

def blocked_by(session, detection_id, marker, uri, rule):
    Detection.objects.create(session=session, detection_id=detection_id, source="modsecurity", signature=rule,
                             timestamp=timezone.now(), marker=marker,
                             raw={"request": {"method": "GET", "uri": uri}, "details": {"ruleId": rule}})

def test_an_answer_is_judged_on_the_server_and_two_wrong_ones_record_a_hint(client):
    session = taught("f4")
    blocked_by(session, "attack", session.browse_marker, "/search/?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E", "941100")
    with patch("api.views._ingest", lambda session, within=None: {}):
        known = check(client, session, "rule", {"answer": "949110"}).json()
        other = check(client, session, "rule", {"answer": "1234"}).json()
        right = check(client, session, "rule", {"answer": " 941100 "}).json()

    assert (known["passed"], known["reason"]) == (False, ["lesson.xss.wrong.rule.949110", []])
    assert (other["passed"], other["reason"], other["hint"]) == (False, ["lesson.check.wrong", []], 1)
    assert other["hints"] == [{"lesson": "f4", "step": "rule", "level": "hint"}], "two wrong answers raise the hint and record it"
    assert right["passed"] is True and right["progress"]["rule"]["passed"]

def test_steps_are_refused_without_an_answer_for_an_unknown_step_a_plain_session_a_closed_one_or_an_unknown_state(client):
    lesson, plain, closed = taught("f6"), board(), taught("f6")
    client.post_json(f"/api/sessions/{closed.pk}/close/")

    for body in ({}, {"answer": "  "}, {"answer": 949110}):
        assert check(client, lesson, "excluded", body).status_code == 400

    assert check(client, lesson, "nowhere").status_code == 404
    assert check(client, plain, "excluded", {"answer": "949110"}).status_code == 400
    assert check(client, closed, "excluded", {"answer": "949110"}).status_code == 409
    assert step(client, lesson, "excluded", body={"state": "done"}).status_code == 400

def test_the_rule_answer_reads_recent_records_and_takes_only_a_browse_record_of_the_attack(client):
    session = taught("f4")
    read = []
    with patch("api.views._ingest", lambda session, within=None: read.append(within)):
        step(client, session, "rule", body={"state": "reached"})
        blocked_by(session, "case", "a-case-uuid", "/search/?q=%3Cscript%3E", "941100")
        blocked_by(session, "other", session.browse_marker, "/search/?q=release", "941100")
        unrelated = check(client, session, "rule", {"answer": "941100"}).json()
        blocked_by(session, "new", session.browse_marker, "/search/?q=%3Cscript%3E", "941100")
        found = check(client, session, "rule", {"answer": "941100"}).json()

    assert (unrelated["passed"], unrelated["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert found["passed"] is True
    assert read == [600, 600], "only recent records, so a session with thousands still finds it"

def test_a_foundation_s_hint_ladder_is_nudge_hint_then_skip_and_never_gives_the_answer(client):
    session = taught("f6")

    pressed = [hint(client, session, "excluded") for _ in range(4)]

    assert [one["hint"] for one in pressed] == [1, 2, 3, 3]
    assert not [one for one in pressed if {"answer", "line"} & set(one["progress"]["excluded"])]
    assert Session.objects.get(pk=session.pk).hints == [{"lesson": "f6", "step": "excluded", "level": "hint"}]

def test_a_worked_scenario_s_ladder_still_gives_the_answer_before_skip(client):
    session = worked("3.1")

    pressed = [hint(client, session, "buffer") for _ in range(5)]

    assert [one["hint"] for one in pressed] == [1, 2, 3, 4, 4]
    assert pressed[2]["progress"]["buffer"]["answer"] == strings.both("scenario.fixrule.answer.buffer")

@pytest.mark.parametrize("mark", views.REPLAY_MARKS)
def test_a_case_an_old_check_verify_replay_or_seed_fired_stays_out_of_both_scores(client, mark):
    session = board()
    now = timezone.now()
    replayed = (("board-sqli-orderby-sqlmap", True),) if mark == "seed" else (
        ("board-sqli-orderby-sqlmap", True), ("board-normal-search-with-apostrophe", False))
    for name, malicious in replayed:
        Case.objects.create(session=session, case_id=f"{mark}-{name}", name=name, malicious=malicious,
                            correlation="marker", started_at=now, ended_at=now, meta={mark: True})

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["tp"] + score["fn"] == 0, "a replay is not an attack case of the score"
    assert score["tn"] + score["fp"] == 0, "a replay is not a benign case of the score"

EXCLUSION = {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}

@pytest.mark.parametrize("tuning, fix", [
    ({"paranoia": 4, "exclusions": [EXCLUSION]}, "path_target"),
    ({"paranoia": 4, "exclusions": [dict(EXCLUSION, path="")]}, "target"),
    ({"paranoia": 4, "exclusions": [dict(EXCLUSION, target="")]}, "rule"),
    ({"paranoia": 3, "exclusions": [EXCLUSION]}, "level"),
    ({"paranoia": 4, "exclusions": []}, None),
])
def test_the_fix_is_named_by_how_narrow_it_is_against_the_session_s_defense(tuning, fix):
    assert views._fix(board(defense="minimal"), tuning) == fix

def http_event(marker, url, at, status=200, src_ip=KALI, dest_ip=WAF):
    return {"event": {"module": "suricata"}, "event_type": "http", "timestamp": at.isoformat(), "@timestamp": at.isoformat(),
            "src_ip": src_ip, "dest_ip": dest_ip,
            "http": {"url": url, "status": status, "http_user_agent": "sqlmap/1.8.4#stable (https://sqlmap.org)",
                     "request_headers": [{"name": "X-Request-ID", "value": marker}] if marker else []}}

def indexed(*events, asked=None):
    def fetched(index, start, end, newest_first):
        if asked is not None:
            asked.append((start, end))
        return [(f"doc-{position}", event) for position, event in enumerate(events)
                if start <= parse_datetime(event["@timestamp"]) <= end], None
    return patch("api.views._fetched", fetched)

def quietly():
    return patch("api.views._ingest", lambda session, within=None: {})

def behind_the_waf():
    return patch("api.views._site_addresses", lambda session: {BOARD})

def run_step(session, lesson_id, step_id, marker, reached):
    steps = {**(session.lesson_steps.get(lesson_id) or {}), step_id: {"reached": reached.isoformat(), "marker": marker}}
    Session.objects.filter(pk=session.pk).update(lesson_steps={**session.lesson_steps, lesson_id: steps})
    session.refresh_from_db()

def recorded_run(session, lesson_id, step_id, marker, started_at, ended_at):
    run_step(session, lesson_id, step_id, marker, started_at - timedelta(seconds=30))
    return Case.objects.create(session=session, case_id=marker, name="board-sqli-orderby-sqlmap-skip-waf", malicious=True,
                               correlation="marker", started_at=started_at, ended_at=ended_at,
                               meta={"kali": step_id, "lesson": lesson_id})

def window_of(discover):
    found = re.search(r"time:\(from:'([^']+)',to:'([^']+)'\)", unquote(discover))
    return parse_datetime(found[1]), parse_datetime(found[2])

def test_a_kali_step_waits_for_the_run_s_last_request_to_settle_then_opens_kibana_on_the_whole_run(client):
    session = taught("f5")
    Session.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=10))
    now = timezone.now()
    run_step(session, "f5", "agent", "agent-run", now - timedelta(minutes=2))
    first, last = now - timedelta(seconds=90), now - timedelta(seconds=40)
    run = [http_event("agent-run", f"/?sort=posts_post.id{n}", at, 403)
           for n, at in enumerate((first, now - timedelta(seconds=70), last))]
    with quietly(), patch.object(kibana, "URL", "http://kibana:5601/kibana"), \
            patch.dict(kibana.VIEWS, {views._session_index(session): (True, 0.0)}):
        with indexed(*run, http_event("agent-run", "/?sort=posts_post.id9", now - timedelta(seconds=3), 403)):
            running = check(client, session, "agent", {"poll": True}).json()
        premature = Case.objects.filter(session=session, case_id="agent-run").exists()
        with indexed(*run):
            done = check(client, session, "agent", {"poll": True}).json()
    recorded = Case.objects.get(session=session, case_id="agent-run")

    assert (running["passed"], running["reason"]) == (False, ["lesson.check.kali_running", ["sqlmap"]])
    assert running["kali"] == {"name": "board-sqli-orderby-sqlmap-random-agent", "running": True}, "no window yet"
    assert premature is False
    assert done["passed"] is True
    assert (recorded.started_at, recorded.ended_at) == (first, last), "the run spans its first to its last request"
    assert window_of(done["kali"]["discover"]) == (first - views.RECORD_SLACK, last + views.RECORD_SLACK)

@pytest.mark.parametrize("word, others, expected", [("word0", ["/search/?q=other"], "3"), ("notes", [], "4")])
def test_the_count_of_my_searches_is_the_events_the_kibana_view_of_this_lesson_shows_for_my_word(
        client, word, others, expected):
    now = timezone.now()
    session = taught("f3", lessons=[{"id": "f2", "started_at": (now - timedelta(minutes=10)).isoformat()},
                                    {"id": "f3", "started_at": (now - timedelta(minutes=3)).isoformat()}])
    searched = [{"at": (now - timedelta(seconds=170)).timestamp(), "method": "GET", "status": 200,
                 "url": f"http://board.com/search/?q={word}"}]
    mine = [http_event(session.browse_marker, f"/search/?q={word}", now - timedelta(seconds=120 - n), 200,
                       src_ip=CUSTOMER, dest_ip=WAF) for n in range(3)]
    upstream = [dict(one, src_ip=WAF, dest_ip=BOARD) for one in mine]
    earlier = http_event(session.browse_marker, f"/search/?q={word}", now - timedelta(minutes=5), 200, src_ip=CUSTOMER)
    seed = http_event("seed-case-uuid", "/search/?q=release notes", now - timedelta(seconds=179), 200, dest_ip=WAF)
    unrelated = [http_event(session.browse_marker, url, now - timedelta(seconds=100), 200, src_ip=CUSTOMER, dest_ip=WAF)
                 for url in ("/?sort=title", *others)]
    with quietly(), behind_the_waf(), indexed(*mine, *upstream, earlier, seed, *unrelated), \
            patch.object(site, "kept", return_value=searched):
        lesson = wargames.lesson("board", lesson_id="f3")
        accepted = views._accepted(session, next(one["check"] for one in lesson["steps"] if one["id"] == "count"), lesson)
        right = check(client, session, "count", {"answer": expected}).json()
        wrong = check(client, session, "count", {"answer": "9"}).json()

    assert accepted == [expected], "my word's http events on the leg that reaches the WAF, as the KQL url : *word* shows them"
    assert right["passed"] is True
    assert (wrong["passed"], wrong["reason"]) == (False, ["lesson.check.wrong", []])

def test_the_rule_that_still_detects_the_random_agent_run_is_a_sql_injection_rule_of_that_run_alone(client):
    session = taught("f5")
    for step_id, marker in (("sqlmap", "probe-run"), ("agent", "agent-run")):
        run_step(session, "f5", step_id, marker, timezone.now() - timedelta(minutes=2))
    for detection_id, marker, rule in (("probe-ua", "probe-run", "913100"), ("probe-sqli", "probe-run", "942190"),
                                       ("agent-sqli", "agent-run", "942100"), ("agent-lfi", "agent-run", "930100"),
                                       ("agent-php", "agent-run", "933160"), ("agent-total", "agent-run", "949110"),
                                       ("mine", session.browse_marker, "941100")):
        blocked_by(session, detection_id, marker, "/?sort=posts_post.id", rule)
    still = next(step["check"] for step in wargames.lesson("board", lesson_id="f5")["steps"] if step["id"] == "still")
    with quietly():
        accepted = views._accepted(session, still)
        judged = {given: check(client, session, "still", {"answer": given}).json()
                  for given in ("930100", "941100", "942190", "913100", "942100")}

    assert accepted == ["942100"]
    assert [judged[given]["passed"] for given in ("930100", "941100", "942190", "942100")] == [False, False, False, True], (
        "not path traversal, not F4's XSS rule, not the first run's rule")
    assert judged["913100"]["reason"] == ["lesson.sqli.wrong.still.913100", []]

def test_waf_records_without_a_rule_are_no_alert_so_a_run_that_drew_only_server_errors_alerted_nobody(client):
    session = taught("f6")
    now = timezone.now()
    recorded_run(session, "f6", "dump", "dump-run", now - timedelta(seconds=90), now - timedelta(seconds=30))
    for position in range(3):
        Detection.objects.create(session=session, detection_id=f"error-{position}", source="modsecurity", signature="",
                                 timestamp=now - timedelta(seconds=60), marker="dump-run",
                                 raw={"request": {"method": "GET", "uri": "/?sort=posts_post.id"}, "details": {}})
    with quietly():
        none = check(client, session, "alerts", {"answer": "none"}).json()
        blocked_by(session, "matched", "dump-run", "/?sort=posts_post.id", "942100")
        waf = check(client, session, "alerts", {"answer": "waf"}).json()

    assert none["passed"] is True
    assert waf["passed"] is True

def waf_record(at, status, marker=None):
    headers = {"X-Request-ID": marker} if marker else {}
    return {"event": {"module": "modsecurity"}, "@timestamp": at.isoformat(),
            "transaction": {"request": {"headers": headers}, "response": {"http_code": status}}}

def test_the_errors_a_run_drew_are_the_waf_log_records_with_status_500_in_the_window_kibana_opens(client):
    session = taught("f6")
    now = timezone.now()
    started, ended = now - timedelta(seconds=90), now - timedelta(seconds=30)
    recorded_run(session, "f6", "dump", "dump-run", started, ended)
    inside = [waf_record(started + timedelta(seconds=10 * n), status, "dump-run" if n % 2 else None)
              for n, status in enumerate((500, 500, 403, 500))]
    suricata = [dict(http_event("dump-run", "/?sort=posts_post.id", started + timedelta(seconds=5), 500))]
    before = waf_record(started - timedelta(seconds=20), 500, "dump-run")
    asked = []
    with quietly(), indexed(*inside, *suricata, before, asked=asked):
        accepted = views._accepted(session, {"kind": "answer", "of": "run_errors", "about": "dump"})
        right = check(client, session, "seen", {"answer": "3"}).json()
        suricata_count = check(client, session, "seen", {"answer": "4"}).json()

    assert accepted == ["3"], "the WAF records with status 500, the number log_source : modsecurity and status : 500 shows"
    assert asked[0] == (started - views.RECORD_SLACK, ended + views.RECORD_SLACK), "the window the Kibana button opens"
    assert right["passed"] is True and suricata_count["passed"] is False

def test_the_cost_question_asks_what_the_admin_objective_would_have_cost_if_detected_not_the_printed_total(client):
    session = taught("f6")
    for key, difficulty in (("board-auth-user-partial", 2), ("board-auth-user-admin", 4), ("board-auth-user-full", 5)):
        Objective.objects.create(session=session, key=key, name=key, difficulty=difficulty, achieved_at=timezone.now())
    with quietly():
        card = client.get(f"/api/sessions/{session.pk}/").json()["lesson_objectives"]
        total = check(client, session, "cost", {"answer": "22"}).json()
        base = check(client, session, "cost", {"answer": "4"}).json()

    assert card["total"] == 22, "the card still shows every objective lost undetected at double points"
    assert (total["passed"], total["reason"]) == (False, ["lesson.check.wrong", []])
    assert base["passed"] is True
