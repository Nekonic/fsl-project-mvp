from defence.models import RuleTest
from lessons.models import Progress
from match.models import Lease, Round
from tests.lessons.conftest import SEARCH_RULE, checked, opened, ran_rule_test
from tests.shape import refused

NOISY_RULE = SEARCH_RULE + 'alert http any any -> any any (msg:"Odd search"; sid:1004; rev:1;)\n'


def through_two(client, problem) -> dict:
    lesson = opened(client, problem)
    assert checked(client, lesson, 1, "placeholder answer").json()["verdict"] == "passed"
    assert checked(client, lesson, 2, "right").json()["verdict"] == "passed"
    return lesson


def test_a_rule_test_check_with_no_test_run_is_not_yet(as_learner, slot, problem):
    lesson = through_two(as_learner, problem)

    assert checked(as_learner, lesson, 3).json() == {"verdict": "not_yet", "detail_code": "no_test", "next": None}


def test_a_rule_test_check_reads_the_seat_s_latest_rule_test_and_the_last_step_ends_the_lesson(as_learner, slot,
                                                                                              problem):
    lesson = through_two(as_learner, problem)
    result = ran_rule_test(as_learner, lesson)
    assert {row["case"]: row["verdict"] for row in result["cases"]}["board-sqli-search"] == "tp"

    answer = checked(as_learner, lesson, 3).json()

    assert RuleTest.objects.filter(round_id=lesson["round"]).count() == 1
    assert answer == {"verdict": "passed", "detail_code": None, "next": None}
    found = Round.objects.get(pk=lesson["round"])
    assert found.phase == "ended" and found.end_reason == "steps_done"
    assert Lease.objects.get(pk=lesson["lease"]).closed is not None


def test_a_rule_test_that_also_alerts_on_benign_traffic_does_not_pass(as_learner, slot, problem):
    lesson = through_two(as_learner, problem)
    slot.defence.node_runner("sensor").fires = {"board-sqli-search": {"1001": "SQL injection in search"},
                                                "board-normal-search": {"1004": "Odd search"}}
    ran_rule_test(as_learner, lesson, NOISY_RULE)

    assert checked(as_learner, lesson, 3).json()["detail_code"] == "benign_alerted"


def test_a_rule_test_that_misses_the_case_does_not_pass(as_learner, slot, problem):
    lesson = through_two(as_learner, problem)
    slot.defence.node_runner("sensor").fires = {}
    ran_rule_test(as_learner, lesson)

    assert checked(as_learner, lesson, 3).json()["detail_code"] == "case_not_detected"


def test_progress_survives_a_lease_close_and_the_next_lesson_round_resumes_where_it_stopped(as_learner, slot, cloud,
                                                                                           problem, learner):
    first = opened(as_learner, problem)
    checked(as_learner, first, 1, "placeholder answer")
    as_learner.post(f"/api/lessons/{first['round']}/end/")
    from match import service as match

    match.advance_refills()
    match.advance_refills()

    second = opened(as_learner, problem)
    shown = as_learner.get(f"/api/lessons/{second['round']}/").json()

    assert second["round"] != first["round"] and second["lease"] != first["lease"]
    assert shown["current"] == 2 and shown["progress"]["passed_order"] == 1
    refused(checked(as_learner, second, 3), 409, "step_locked")
    assert checked(as_learner, second, 1, "wrong").json()["verdict"] == "not_yet"
    assert Progress.objects.get(user=learner, problem=problem).passed_order == 1
    assert checked(as_learner, second, 2, "right").json() == {"verdict": "passed", "detail_code": None, "next": 3}


def test_the_start_posture_is_not_an_apply_and_the_seat_s_own_apply_passes_rule_applied(as_learner, slot,
                                                                                        applying_problem):
    lesson = through_two(as_learner, applying_problem)
    ran_rule_test(as_learner, lesson)
    assert checked(as_learner, lesson, 3).json()["verdict"] == "passed"
    base = f"/api/rounds/{lesson['round']}/defence/waf/"
    version = as_learner.get(base).json()["version"]

    before = checked(as_learner, lesson, 4).json()
    applied = as_learner.post(f"{base}apply/", {"posture": {"paranoia": 3}, "base_version": version}, format="json")
    after = checked(as_learner, lesson, 4).json()

    assert before["detail_code"] == "not_applied"
    assert applied.status_code == 200, applied.content
    assert after["verdict"] == "passed"


def test_staff_try_a_step_against_an_ended_round_of_the_same_wargame(as_learner, second_browser, slot, problem, staff):
    lesson = through_two(as_learner, problem)
    ran_rule_test(as_learner, lesson)
    route = f"/api/staff/steps/{problem.pk}/3/try/"
    second_browser.force_authenticate(staff)

    running = second_browser.post(route, {"round": lesson["round"]}, format="json")
    as_learner.post(f"/api/lessons/{lesson['round']}/end/")
    tried = second_browser.post(route, {"round": lesson["round"]}, format="json")

    refused(running, 409, "round_running")
    assert tried.json() == {"verdict": "passed", "detail_code": None, "next": None}
    refused(as_learner.post(route, {"round": lesson["round"]}, format="json"), 403, "not_staff")


def test_checking_an_earlier_step_again_does_not_move_when_the_later_step_opened(as_learner, slot, applying_problem):
    lesson = through_two(as_learner, applying_problem)
    ran_rule_test(as_learner, lesson)
    assert checked(as_learner, lesson, 3).json()["verdict"] == "passed"
    base = f"/api/rounds/{lesson['round']}/defence/waf/"
    version = as_learner.get(base).json()["version"]
    applied = as_learner.post(f"{base}apply/", {"posture": {"paranoia": 3}, "base_version": version}, format="json")
    assert applied.status_code == 200, applied.content

    assert checked(as_learner, lesson, 1, "placeholder answer").json()["verdict"] == "passed"
    assert checked(as_learner, lesson, 3).json()["verdict"] == "passed"

    assert checked(as_learner, lesson, 4).json()["verdict"] == "passed"
