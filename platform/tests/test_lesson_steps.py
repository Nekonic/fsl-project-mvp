import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

import wargames
from api import site, views
from api.models import Case, Detection, Session
from console import strings

pytestmark = pytest.mark.django_db

TRUTH = json.loads((Path(__file__).resolve().parent / "fixtures" / "board-auth-users.json").read_text())
EXCLUSION = {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}
MISSED = {"paranoia": 1, "exclusions": [{"rule_id": 949110, "target": "", "path": ""},
                                        {"rule_id": 959100, "target": "", "path": ""}]}

def board(**fields):
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), **fields)

def taught(lesson_id):
    return board(guidance=True, lesson=lesson_id, defense=wargames.lesson_defense("board", lesson_id))

def worked(scenario_id):
    return board(guidance=True, lesson=scenario_id, course_scenario=scenario_id,
                 defense=wargames.scenario_run(scenario_id)["defense"])

def step(client, session, step_id, tail="", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def check(client, session, step_id, body=None):
    return step(client, session, step_id, "check/", body)

def in_force():
    return patch("api.views._waf_in_force", return_value=MISSED)

def test_the_session_payload_carries_no_answer_key(client):
    attack, fixrule = taught("f5"), worked("3.1")

    steps = {shown["id"]: shown["check"] for shown in client.get(f"/api/sessions/{attack.pk}/").json()["lesson"]["steps"]}
    fixing = {shown["id"]: shown for shown in client.get(f"/api/sessions/{fixrule.pk}/").json()["lesson"]["steps"]}

    assert steps["rule"] == {"kind": "answer"}
    assert steps["attack"] == {"kind": "sent", "match": "1=1"}
    assert steps["sqlmap"] == {"kind": "kali", "case": "board-sqli-orderby-sqlmap"}
    assert fixing["buffer"]["check"] == {"kind": "choice", "options": ["http.uri", "http.request_body", "http.header",
                                                                      "http.cookie"]}
    assert fixing["fix"]["check"] == {"kind": "rules"} and "rule" not in fixing["fix"]

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

    assert command == f"cat {settings.FSL_WAF.rules}"
    assert reached["progress"]["excluded"]["command"] == command
    assert shown["excluded"]["command"] == command
    assert "command" not in shown["lost"] and "command" not in reached["progress"].get("lost", {})

def test_the_answer_text_arrives_at_the_answer_hint_level_in_both_languages(client):
    session = taught("f6")

    before = [hint(client, session, "excluded")["progress"]["excluded"] for _ in range(2)]
    third = hint(client, session, "excluded")["progress"]["excluded"]

    assert all("answer" not in record for record in before)
    assert third["hint"] == 3
    assert third["answer"] == strings.both("lesson.miss.answer.excluded")
    assert set(third["answer"]) == set(strings.LANGUAGES)
    assert client.get(f"/api/sessions/{session.pk}/").json()["progress"]["excluded"]["answer"] == third["answer"]

def test_a_step_s_line_arrives_in_the_check_response_that_passes_it(client):
    session = taught("f6")
    with in_force():
        wrong = check(client, session, "excluded", {"answer": "942100"}).json()
        right = check(client, session, "excluded", {"answer": "949110"}).json()

    assert "line" not in wrong["progress"]["excluded"]
    assert right["progress"]["excluded"]["line"] == strings.both("lesson.miss.line.excluded")

def test_a_step_reached_then_left_unpassed_is_recorded_skipped_and_a_passed_one_is_not(client):
    session = taught("f1")

    step(client, session, "entry", body={"state": "reached"})
    skipped = step(client, session, "entry", body={"state": "skipped"}).json()["progress"]["entry"]
    step(client, session, "map", body={"state": "reached"})
    check(client, session, "map")
    passed = step(client, session, "map", body={"state": "skipped"}).json()["progress"]["map"]

    assert skipped["reached"] and skipped["skipped"] and skipped["passed"] is None
    assert passed["passed"] and passed["skipped"] is None, "moving on from a passed step is not skipping it"
    assert client.get(f"/api/sessions/{session.pk}/").json()["progress"]["entry"]["skipped"] == skipped["skipped"]

def blocked_by(session, detection_id, marker, uri, rule):
    Detection.objects.create(session=session, detection_id=detection_id, source="modsecurity", signature=rule,
                             timestamp=timezone.now(), marker=marker,
                             raw={"request": {"method": "GET", "uri": uri}, "details": {"ruleId": rule}})

def test_an_answer_is_judged_on_the_server_and_two_wrong_ones_record_a_hint(client):
    session = taught("f5")
    blocked_by(session, "attack", session.browse_marker, "/search/?q=%27%20OR%201%3D1--", "942100")
    with patch("api.views._ingest", lambda session, within=None: {}):
        known = check(client, session, "rule", {"answer": "949110"}).json()
        other = check(client, session, "rule", {"answer": "1234"}).json()
        right = check(client, session, "rule", {"answer": " 942100 "}).json()

    assert (known["passed"], known["reason"]) == (False, ["lesson.attack.wrong.rule.949110", []])
    assert (other["passed"], other["reason"], other["hint"]) == (False, ["lesson.check.wrong", []], 1)
    assert other["hints"] == [{"step": "rule", "level": "hint"}], "two wrong answers raise the hint and record it"
    assert right["passed"] is True and right["progress"]["rule"]["passed"]

def test_a_choice_outside_the_answer_fails_and_the_right_one_passes(client):
    session = worked("3.1")

    assert check(client, session, "buffer", {"answer": "http.request_body"}).json()["passed"] is False
    assert check(client, session, "buffer", {"answer": "http.uri"}).json()["passed"] is True

@pytest.mark.parametrize("body", [{}, {"answer": "  "}, {"answer": 949110}])
def test_an_answer_step_checked_without_an_answer_is_refused(client, body):
    assert check(client, taught("f6"), "excluded", body).status_code == 400

def test_steps_are_refused_for_an_unknown_step_a_plain_session_a_closed_one_or_an_unknown_state(client):
    lesson, plain, closed = taught("f6"), board(), taught("f6")
    client.post_json(f"/api/sessions/{closed.pk}/close/")

    assert check(client, lesson, "nowhere").status_code == 404
    assert check(client, plain, "excluded", {"answer": "949110"}).status_code == 400
    assert check(client, closed, "excluded", {"answer": "949110"}).status_code == 409
    assert step(client, lesson, "excluded", body={"state": "done"}).status_code == 400

def test_the_rule_answer_reads_recent_records_and_takes_only_a_browse_record_of_the_attack(client):
    session = taught("f5")
    read = []
    with patch("api.views._ingest", lambda session, within=None: read.append(within)):
        step(client, session, "rule", body={"state": "reached"})
        blocked_by(session, "case", "a-case-uuid", "/search/?q=%27%20OR%201%3D1--", "942100")
        blocked_by(session, "other", session.browse_marker, "/search/?q=release", "942100")
        unrelated = check(client, session, "rule", {"answer": "942100"}).json()
        blocked_by(session, "new", session.browse_marker, "/search/?q=%27%20OR%201%3D1--", "942100")
        found = check(client, session, "rule", {"answer": "942100"}).json()

    assert (unrelated["passed"], unrelated["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert found["passed"] is True
    assert read == [600, 600], "only recent records, so a session with thousands still finds it"

def test_a_hint_press_raises_the_step_s_hint_level_and_records_the_first_once(client):
    session = taught("f6")
    hints = f"/api/sessions/{session.pk}/lesson/hints/"

    levels = [client.post_json(hints, {"step": "excluded", "level": "hint"}).json()["hint"] for _ in range(5)]

    assert levels == [1, 2, 3, 4, 4]
    assert Session.objects.get(pk=session.pk).hints == [{"step": "excluded", "level": "hint"}]

def test_do_it_for_me_answers_on_the_server_and_is_recorded_as_such(client):
    session = taught("f6")
    with in_force():
        done = step(client, session, "excluded", "do/").json()

    assert done["passed"] is True
    assert done["progress"]["excluded"]["done_for_me"] is True and done["progress"]["excluded"]["passed"]
    assert done["hints"] == [{"step": "excluded", "level": "do"}]
    assert "lesson" not in client.get(f"/api/sessions/{session.pk}/").json()["result"]

def test_do_it_for_me_on_the_rules_step_adds_the_rule_through_the_sensor_and_checks_it(client):
    session = worked("3.1")
    posture = (Path(settings.FSL_SOURCE) / "deploy/suricata/rules/broken-sort.rules").read_text()
    rule = next(shown["rule"] for shown in wargames.lesson("board", lesson_id="3.1")["steps"] if shown["id"] == "fix")
    applied = []
    with patch("api.views._live_rules", side_effect=lambda session=None: applied[-1] if applied else posture), \
            patch("api.views._apply", lambda content, session=None: applied.append(content)):
        done = step(client, session, "fix", "do/").json()

    assert done["passed"] is True and done["progress"]["fix"]["done_for_me"] is True
    assert applied == [f"{posture.rstrip()}\n{rule.strip()}\n"]

def test_do_it_for_me_on_a_step_only_the_console_can_perform_records_it_and_passes_nothing(client):
    session = taught("f5")
    with patch.object(site, "kept", return_value=[]):
        done = step(client, session, "attack", "do/").json()

    assert (done["passed"], done["reason"]) == (False, ["lesson.attack.fail.attack", []])
    assert done["progress"]["attack"]["done_for_me"] is True

@pytest.mark.parametrize("mark", views.REPLAY_MARKS)
def test_a_case_an_old_check_verify_replay_or_seed_fired_stays_out_of_both_scores(client, mark):
    session = board()
    now = timezone.now()
    for name, malicious in (("board-sqli-orderby-sqlmap", True), ("board-normal-search-with-apostrophe", False)):
        Case.objects.create(session=session, case_id=f"{mark}-{name}", name=name, malicious=malicious,
                            started_at=now, ended_at=now, meta={mark: True})

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["tp"] + score["fn"] == 0, "a replay is not an attack case of the score"
    assert score["tn"] + score["fp"] == 0, "a replay is not a benign case of the score"

@pytest.mark.parametrize("tuning, fix", [
    ({"paranoia": 4, "exclusions": [EXCLUSION]}, "path_target"),
    ({"paranoia": 4, "exclusions": [dict(EXCLUSION, path="/")]}, "path_target"),
    ({"paranoia": 4, "exclusions": [dict(EXCLUSION, path="")]}, "target"),
    ({"paranoia": 4, "exclusions": [dict(EXCLUSION, target="")]}, "rule"),
    ({"paranoia": 3, "exclusions": [EXCLUSION]}, "level"),
    ({"paranoia": 4, "exclusions": []}, None),
])
def test_the_fix_is_named_by_how_narrow_it_is_against_the_session_s_defense(tuning, fix):
    session = board(defense="minimal")

    assert views._fix(session, tuning) == fix
