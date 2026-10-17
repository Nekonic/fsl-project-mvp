import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

import wargames
from api import views
from api.models import Case, Detection, Session
from console import strings

pytestmark = pytest.mark.django_db

TRUTH = json.loads((Path(__file__).resolve().parent / "fixtures" / "board-auth-users.json").read_text())

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
    assert other["hints"] == [{"lesson": "f5", "step": "rule", "level": "hint"}], "two wrong answers raise the hint and record it"
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

def test_a_hint_press_raises_the_step_s_hint_level_records_the_first_once_and_gives_the_answer_at_its_level(client):
    session = taught("f6")

    pressed = [hint(client, session, "excluded") for _ in range(5)]

    assert [one["hint"] for one in pressed] == [1, 2, 3, 4, 4]
    assert all("answer" not in one["progress"]["excluded"] for one in pressed[:2])
    assert pressed[2]["progress"]["excluded"]["answer"] == strings.both("lesson.miss.answer.excluded")
    assert Session.objects.get(pk=session.pk).hints == [{"lesson": "f6", "step": "excluded", "level": "hint"}]

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
