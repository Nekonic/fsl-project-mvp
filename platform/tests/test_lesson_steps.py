from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Case, Detection, Session
from rules import crs
from tests.test_lesson_api import HELD, Stand, attacker, board

pytestmark = pytest.mark.django_db

O_BRIEN = "board-normal-search-with-apostrophe"
EXCLUSION = {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}

def step(client, session, step_id, tail="", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def check(client, session, step_id, body=None):
    return step(client, session, step_id, "check/", body)

def test_the_session_payload_carries_no_answer_key(client):
    session = board(guidance=True)

    steps = {shown["id"]: shown["check"] for shown in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert steps["rule"] == {"kind": "answer"}
    assert steps["target"] == {"kind": "choice", "options": ["ARGS:q", "REQUEST_URI", "REQUEST_COOKIES", "REQUEST_HEADERS"]}
    assert steps["exclude"] == {"kind": "waf"}
    assert steps["retry"] == {"kind": "served", "path": "O'Brien"}
    assert steps["search"] == {"kind": "alert", "path": "O'Brien"}

def test_a_step_reached_then_left_unpassed_is_recorded_skipped_and_a_passed_one_is_not(client):
    session = board(guidance=True)

    step(client, session, "rule", body={"state": "reached"})
    skipped = step(client, session, "rule", body={"state": "skipped"}).json()["progress"]["rule"]
    step(client, session, "target", body={"state": "reached"})
    check(client, session, "target", {"answer": "ARGS:q"})
    passed = step(client, session, "target", body={"state": "skipped"}).json()["progress"]["target"]

    assert skipped["reached"] and skipped["skipped"] and skipped["passed"] is None
    assert passed["passed"] and passed["skipped"] is None, "moving on from a passed step is not skipping it"
    assert client.get(f"/api/sessions/{session.pk}/").json()["progress"]["rule"]["skipped"] == skipped["skipped"]

def test_an_answer_is_judged_on_the_server_and_two_wrong_ones_record_a_hint(client):
    session = board(guidance=True)

    known = check(client, session, "rule", {"answer": "949110"}).json()
    other = check(client, session, "rule", {"answer": "1234"}).json()
    right = check(client, session, "rule", {"answer": " 920273 "}).json()

    assert (known["passed"], known["reason"]) == (False, ["lesson.board.wrong.rule.949110", []])
    assert (other["passed"], other["reason"], other["hint"]) == (False, ["lesson.check.wrong", []], 1)
    assert other["hints"] == [{"step": "rule", "level": "hint"}], "two wrong answers raise the hint and record it"
    assert right["passed"] is True and right["progress"]["rule"]["passed"]

def test_a_choice_outside_the_answer_fails_and_the_right_one_passes(client):
    session = board(guidance=True)

    assert check(client, session, "target", {"answer": "REQUEST_URI"}).json()["passed"] is False
    assert check(client, session, "target", {"answer": "ARGS:q"}).json()["passed"] is True

@pytest.mark.parametrize("body", [{}, {"answer": "  "}, {"answer": 920273}])
def test_an_answer_step_checked_without_an_answer_is_refused(client, body):
    assert check(client, board(guidance=True), "rule", body).status_code == 400

def test_steps_are_refused_for_an_unknown_step_a_plain_session_a_closed_one_or_an_unknown_state(client):
    lesson, plain, closed = board(guidance=True), board(), board(guidance=True)
    client.post_json(f"/api/sessions/{closed.pk}/close/")

    assert check(client, lesson, "nowhere").status_code == 404
    assert check(client, plain, "rule", {"answer": "920273"}).status_code == 400
    assert check(client, closed, "rule", {"answer": "920273"}).status_code == 409
    assert step(client, lesson, "rule", body={"state": "done"}).status_code == 400

def test_the_waf_check_reads_the_file_then_replays_the_o_brien_search_marked_as_a_check(client):
    session = board(guidance=True)
    stand = Stand()
    stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 4, "exclusions": [EXCLUSION]})
    fire, fired = attacker({})
    with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
        first = check(client, session, "exclude", {"poll": True}).json()
        again = check(client, session, "exclude", {"poll": True}).json()

    assert first["passed"] is True
    assert fired == [O_BRIEN], "a poll on an unchanged file does not replay again"
    assert again["passed"] is False and again["reason"] == ["lesson.board.fail.exclude.reload", []]
    assert Case.objects.get().meta["check"] == "exclude"
    score = client.get(f"/api/sessions/{session.pk}/score/").json()
    assert score["tn"] == score["fp"] == 0, "a check's replay is not a benign case of the score"

def test_the_waf_check_fails_on_a_file_without_the_exclusion_and_replays_nothing(client):
    session = board(guidance=True)
    fire, fired = attacker({})
    with patch("range.docker.Docker.runner", Stand().runner()), patch("api.views.harness.fire", fire):
        answer = check(client, session, "exclude").json()

    assert (answer["passed"], answer["reason"]) == (False, ["lesson.board.fail.exclude", []])
    assert fired == []

def test_the_served_check_replays_the_case_and_says_the_status_it_got(client):
    session = board(guidance=True)
    fire, _ = attacker({O_BRIEN: "http_code=403\n"})
    with patch("api.views.harness.fire", fire):
        blocked = check(client, session, "retry").json()
    fire, _ = attacker({})
    with patch("api.views.harness.fire", fire):
        served = check(client, session, "retry").json()

    assert (blocked["passed"], blocked["reason"]) == (False, ["lesson.board.fail.retry", [403]])
    assert served["passed"] is True
    assert all(case.meta["check"] == "retry" for case in Case.objects.all())

def test_the_alert_check_reads_recent_records_and_takes_only_a_new_browse_record_of_the_search(client):
    session = board(guidance=True)
    now = timezone.now()

    def alert(detection_id, marker, url):
        Detection.objects.create(session=session, detection_id=detection_id, source="modsecurity", signature="920273",
                                 timestamp=now, marker=marker, raw={"request": {"method": "GET", "uri": url}})

    alert("old", session.browse_marker, "/search/?q=O%27Brien")
    read = []
    with patch("api.views._ingest", lambda session, within=None: read.append(within)):
        step(client, session, "search", body={"state": "reached"})
        earlier = check(client, session, "search", {"poll": True}).json()["passed"]
        alert("case", "a-case-uuid", "/search/?q=O%27Brien")
        alert("other", session.browse_marker, "/search/?q=release")
        unrelated = check(client, session, "search", {"poll": True}).json()["passed"]
        alert("new", session.browse_marker, "/search/?q=O%27Brien")
        found = check(client, session, "search", {"poll": True}).json()

    assert (earlier, unrelated, found["passed"]) == (False, False, True)
    assert read == [600, 600, 600], "only recent records, so a session with thousands still finds it"
    assert found["hint"] == 0, "a failed poll is not a wrong answer"

def test_the_verify_step_passes_once_the_last_verify_passed(client):
    session = board(guidance=True)
    before = check(client, session, "verify").json()
    fire, _ = attacker({"board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD})
    with patch("api.views.harness.fire", fire):
        client.post_json(f"/api/sessions/{session.pk}/verify/")

    assert (before["passed"], before["reason"]) == (False, ["lesson.board.fail.verify", []])
    assert check(client, session, "verify").json()["passed"] is True

def test_a_hint_press_raises_the_step_s_hint_level_and_records_the_first_once(client):
    session = board(guidance=True)
    hints = f"/api/sessions/{session.pk}/lesson/hints/"

    levels = [client.post_json(hints, {"step": "rule", "level": "hint"}).json()["hint"] for _ in range(5)]

    assert levels == [1, 2, 3, 4, 4]
    assert Session.objects.get(pk=session.pk).hints == [{"step": "rule", "level": "hint"}]

def test_do_it_for_me_answers_on_the_server_and_is_recorded_as_such(client):
    session = board(guidance=True)

    done = step(client, session, "rule", "do/").json()

    assert done["passed"] is True
    assert done["progress"]["rule"]["done_for_me"] is True and done["progress"]["rule"]["passed"]
    assert done["hints"] == [{"step": "rule", "level": "do"}]
    assert client.get(f"/api/sessions/{session.pk}/").json()["result"]["lesson"] is None

def test_do_it_for_me_on_the_exclusion_step_adds_it_through_the_waf_api_and_checks_it(client):
    session = board(guidance=True, waf={"paranoia": 4, "exclusions": []})
    stand = Stand()
    stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 4, "exclusions": []})
    fire, fired = attacker({})
    with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
        done = step(client, session, "exclude", "do/").json()

    assert done["passed"] is True and done["progress"]["exclude"]["done_for_me"] is True
    assert Session.objects.get(pk=session.pk).waf == {"paranoia": 4, "exclusions": [EXCLUSION]}
    assert fired == [O_BRIEN]

def test_do_it_for_me_on_a_step_only_the_console_can_perform_records_it_and_passes_nothing(client):
    session = board(guidance=True)

    done = step(client, session, "search", "do/").json()

    assert (done["passed"], done["reason"]) == (False, None)
    assert done["progress"]["search"]["done_for_me"] is True

def test_a_practice_session_shows_no_command_and_refuses_hints_and_done_for_me(client):
    fire, _ = attacker({})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"lesson": "waf-exclusion", "mode": "self"}).json()
    session = Session.objects.get(pk=opened["id"])

    steps = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    hint = client.post_json(f"/api/sessions/{session.pk}/lesson/hints/", {"step": "rule", "level": "hint"})
    done = step(client, session, "rule", "do/")

    assert opened["mode"] == "self"
    assert not any("command" in shown for shown in steps), "in practice the learner types the command"
    assert (hint.status_code, done.status_code) == (409, 409)
    assert check(client, session, "rule", {"answer": "920273"}).json()["passed"] is True

def test_the_mode_is_switched_by_patch_and_each_verify_run_keeps_the_mode_it_ran_in(client):
    session = board(guidance=True)
    fire, _ = attacker({"board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD})
    with patch("api.views.harness.fire", fire):
        guided = client.post_json(f"/api/sessions/{session.pk}/verify/").json()
        switched = client.patch(f"/api/sessions/{session.pk}/", {"mode": "self"}, content_type="application/json")
        practised = client.post_json(f"/api/sessions/{session.pk}/verify/").json()

    assert switched.status_code == 200 and switched.json()["mode"] == "self"
    assert (guided["mode"], practised["mode"]) == ("guided", "self")
    assert client.get(f"/api/sessions/{session.pk}/").json()["result"]["lesson"]["mode"] == "self"

@pytest.mark.parametrize("guidance, body, status", [
    (True, {"mode": "alone"}, 400),
    (False, {"mode": "self"}, 400),
])
def test_a_mode_that_is_not_one_or_a_session_that_is_not_a_lesson_is_refused(client, guidance, body, status):
    session = board(guidance=guidance)

    answer = client.patch(f"/api/sessions/{session.pk}/", body, content_type="application/json")

    assert answer.status_code == status
    assert Session.objects.get(pk=session.pk).mode == "guided"

def test_a_wargame_cannot_be_opened_in_self_mode(client):
    answer = client.post_json("/api/sessions/", {"mode": "self"})

    assert answer.status_code == 400 and "mode" in answer.json()["detail"]
