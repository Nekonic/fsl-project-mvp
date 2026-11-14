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
import lesson
import wargames
from api import site, views
from api.models import Case, Detection, Objective, Session
from console import strings
from range.interfaces import Interface

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
    return {encoded(text) for key, text in strings.withheld().items() if key.startswith(f"{prefix}.")}

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

    assert command == f"grep -n ruleRemove {settings.CR_WAF.rules}"
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
    assert pressed[2]["progress"]["buffer"]["answer"] == strings.line("scenario.fixrule.answer.buffer")

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

    assert (running["passed"], running["reason"]) == (False, ["lesson.check.kali_settling", ["sqlmap"]])
    assert running["kali"] == {"name": "board-sqli-orderby-sqlmap-random-agent", "settling": True}, "no window yet"
    assert premature is False
    assert done["passed"] is True
    assert (recorded.started_at, recorded.ended_at) == (first, last), "the run spans its first to its last request"
    assert window_of(done["kali"]["discover"]) == (first - views.RECORD_SLACK, last + views.RECORD_SLACK)

def test_a_fact_about_a_kali_step_that_recorded_nothing_sends_the_learner_back_to_that_step(client):
    session = taught("f5")
    run_step(session, "f5", "verdict", "unused", timezone.now())
    with quietly():
        before = check(client, session, "verdict", {"answer": "yes"}).json()
        recorded_run(session, "f5", "sqlmap", "sqlmap-run", timezone.now() - timedelta(minutes=2),
                     timezone.now() - timedelta(minutes=1))
        with patch("api.views.attacker.sqlmap_found", return_value=True), patch("api.views._range"):
            after = check(client, session, "verdict", {"answer": "yes"}).json()

    assert (before["passed"], before["reason"]) == (False, ["lesson.check.kali_first", []])
    assert after["passed"] is True

@pytest.mark.parametrize("word, others, expected", [("word0", ["/search/?q=other"], "6"), ("notes", [], "7")])
def test_the_count_of_my_searches_is_the_http_events_of_both_legs_the_kibana_view_of_this_lesson_shows_for_my_word(
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

    assert accepted == [expected], (
        "my word's http events on both legs, as event_type : http and url : *word* shows them, not the searches I made")
    assert right["passed"] is True
    assert (wrong["passed"], wrong["reason"]) == (False, ["lesson.check.wrong", []])

def test_the_last_f5_step_asks_whether_the_scanner_rule_matched_the_random_agent_run_from_that_run_s_records(client):
    session = taught("f5")
    now = timezone.now()
    recorded_run(session, "f5", "sqlmap", "probe-run", now - timedelta(minutes=4), now - timedelta(minutes=3))
    recorded_run(session, "f5", "agent", "agent-run", now - timedelta(minutes=2), now - timedelta(minutes=1))
    for detection_id, marker, rule in (("probe-ua", "probe-run", "913100"), ("probe-sqli", "probe-run", "942190"),
                                       ("agent-sqli", "agent-run", "942100"), ("agent-total", "agent-run", "949110"),
                                       ("mine", session.browse_marker, "913100")):
        blocked_by(session, detection_id, marker, "/?sort=posts_post.id", rule)
    still = next(step["check"] for step in wargames.lesson("board", lesson_id="f5")["steps"] if step["id"] == "still")
    with quietly():
        accepted = views._accepted(session, still)
        judged = {given: check(client, session, "still", {"answer": given}).json() for given in ("present", "absent")}
        blocked_by(session, "agent-ua", "agent-run", "/?sort=posts_post.id", "913100")
        kept_its_agent = views._accepted(session, still)

    assert (still["kind"], still["options"]) == ("choice", ["present", "absent"])
    assert accepted == ["absent"], "913100 matched the first run and the learner's own request, not this run"
    assert (judged["present"]["passed"], judged["present"]["reason"]) == (False, ["lesson.check.wrong", []])
    assert judged["absent"]["passed"] is True
    assert kept_its_agent == ["present"], "a run that kept sqlmap's User-Agent drew 913100, and the answer follows"

def test_whether_a_rule_matched_a_run_waits_for_the_run_to_be_recorded(client):
    session = taught("f5")
    run_step(session, "f5", "agent", "agent-run", timezone.now() - timedelta(minutes=2))
    still = next(step["check"] for step in wargames.lesson("board", lesson_id="f5")["steps"] if step["id"] == "still")
    with quietly():
        unrecorded = check(client, session, "still", {"answer": "absent"}).json()
        recorded_run(session, "f5", "agent", "agent-run", timezone.now() - timedelta(minutes=2), timezone.now())
        silent = views._accepted(session, still)

    assert (unrecorded["passed"], unrecorded["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert silent == ["absent"], "a recorded run the WAF matched no rule on did not match 913100 either"

def test_a_recorded_run_s_facts_are_read_without_ingesting_again_once_its_records_are_held(client):
    session = taught("f5")
    now = timezone.now()
    recorded_run(session, "f5", "sqlmap", "probe-run", now - timedelta(minutes=2), now - timedelta(minutes=1))
    steps = {step["id"]: step["check"] for step in wargames.lesson("board", lesson_id="f5")["steps"]}
    ingested = []
    with patch("api.views._ingest", lambda session, within=None: ingested.append(within) or {}):
        before = views._accepted(session, steps["scanner"])
        blocked_by(session, "probe-ua", "probe-run", "/?sort=posts_post.id", "913100")
        Detection.objects.filter(detection_id="probe-ua").update(src_ip="5.188.10.10")
        held = [views._accepted(session, steps[name]) for name in ("scanner", "source", "scanner")]

    assert before == [] and len(ingested) == 1, "nothing of the run held yet, so the check ingests"
    assert held == [["913100"], ["5.188.10.10"], ["913100"]]
    assert len(ingested) == 1, "the run ended and settled before it was recorded, so its records do not change"

def test_the_slot_s_interfaces_read_for_the_map_answer_the_session_s_address_questions_until_it_closes(client):
    session = taught("f1")
    reads = []

    class Slot:
        def interfaces(self, hosts):
            reads.append(hosts)
            return [Interface("cr-wargame-host", "ens3", "10.30.0.48/24", "estate")] if len(reads) > 1 else []

    with patch("api.views._range", lambda session=None, adapter=None: Slot()):
        unreachable = views._map_found(session)
        views._map_read(session)()
        kept = [views._map_found(session) for _ in range(3)]
        with patch("api.views._range_fact", lambda session, check, taught: []):
            views._accepted(session, {"of": "address", "host": "board.com"})
        dropped = session.pk not in views._found_kept
        views._map_read(session)()
    client.post_json(f"/api/sessions/{session.pk}/close/")

    assert unreachable == [] and len(reads) == 3, "an empty read is not kept; three checks read nothing"
    assert all(found == kept[0] and found for found in kept), "the map's read at open answers each check"
    assert dropped, "an address question the kept read cannot answer reads the slot again"
    assert session.pk not in views._found_kept, "a closed session's slot is reset for the next one"

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

def waf_record(at, status, marker=None, rules=(), client=KALI):
    headers = {"X-Request-ID": marker} if marker else {}
    return {"event": {"module": "modsecurity"}, "@timestamp": at.isoformat(),
            "transaction": {"client_ip": client, "request": {"headers": headers}, "response": {"http_code": status},
                            "messages": [{"message": "matched", "details": {"ruleId": rule}} for rule in rules]}}

def test_the_trace_question_asks_how_many_500_records_the_run_left_in_the_window_kibana_opens(client):
    session = taught("f6")
    now = timezone.now()
    started, ended = now - timedelta(seconds=90), now - timedelta(seconds=30)
    recorded_run(session, "f6", "dump", "dump-run", started, ended)
    inside = [waf_record(started + timedelta(seconds=10 * n), status, "dump-run" if n % 2 else None)
              for n, status in enumerate((500, 500, 500))]
    blocked = waf_record(started + timedelta(seconds=40), 403, "dump-run", rules=("942100",), client=CUSTOMER)
    before = waf_record(started - timedelta(seconds=20), 500, client=CUSTOMER)
    seen = next(step["check"] for step in wargames.lesson("board", lesson_id="f6")["steps"] if step["id"] == "seen")
    asked = []
    with quietly(), indexed(*inside, blocked, before, asked=asked):
        accepted = views._accepted(session, seen)
        right = check(client, session, "seen", {"answer": "3"}).json()
        ruled = check(client, session, "seen", {"answer": "-"}).json()
        sourced = check(client, session, "seen", {"answer": KALI}).json()

    assert accepted == ["3"], "the run's 500 records; a 403 and a record before the run are not counted"
    assert asked[0] == (started - views.RECORD_SLACK, ended + views.RECORD_SLACK), "the window the Kibana button opens"
    assert right["passed"] is True
    assert ruled["passed"] is False and ruled["reason"] == ["lesson.miss.wrong.seen.rule_id", []]
    assert sourced["passed"] is False and sourced["reason"] == ["lesson.miss.wrong.seen.address", []], (
        "the attacker's address is on the map and was asked in the lesson before, so it is no longer the question")

def test_only_500_records_name_a_source_for_the_trace_question():
    records = [{"transaction": {"client_ip": KALI, "response": {"http_code": 500}}},
               {"transaction": {"client_ip": KALI, "response": {"http_code": "500"}}},
               {"transaction": {"client_ip": CUSTOMER, "response": {"http_code": 403}}},
               {"transaction": {"response": {"http_code": 500}}}]

    assert lesson.server_error_sources(records) == [KALI]

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
