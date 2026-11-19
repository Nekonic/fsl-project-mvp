from events import log
from lessons.models import StepResult
from match.models import Lease, Round, Seat
from tests.lessons.conftest import checked, opened
from tests.shape import refused
from testing import factories


def kinds(round_id):
    return [event["kind"] for event in log.after(round_id, 0, log.Viewer(staff=True)).events]


def test_opening_a_lesson_seats_the_learner_on_every_side_the_problem_needs_and_starts_the_round(
        as_learner, slot, problem, learner):
    lesson = opened(as_learner, problem)

    found = Round.objects.get(pk=lesson["round"])
    assert lesson["phase"] == "ready" and found.kind == "lesson" and found.phase == "running"
    assert Lease.objects.get(pk=lesson["lease"]).purpose == "lesson"
    assert sorted(Seat.objects.filter(round=found, user=learner).values_list("side", flat=True)) == [
        "attack", "defence"]


def test_a_lesson_shows_its_steps_without_any_answer_and_starts_at_the_first(as_learner, slot, problem):
    lesson = opened(as_learner, problem)

    shown = as_learner.get(f"/api/lessons/{lesson['round']}/").json()

    assert shown["current"] == 1 and shown["progress"] == {"passed_order": 0, "passed_at": None}
    assert shown["phase"] == "ready" and shown["problem"]["title"] == "Placeholder lesson"
    assert [set(step) for step in shown["steps"]] == [{"order", "body", "opens", "hints_available"}] * 3
    assert [step["hints_available"] for step in shown["steps"]] == [2, 0, 0]
    assert "placeholder answer" not in str(shown) and "accept" not in str(shown)


def test_a_round_problem_cannot_be_opened_as_a_lesson(as_learner, slot, db):
    from content import service as content

    document = factories.round_problem(objectives=["board-auth-user-admin"])
    document["problem"]["published"] = True
    found = content.save_document(document)

    refused(as_learner.post("/api/lessons/", {"problem": found.pk}, format="json"), 400, "invalid_choice",
            path="problem")
    assert not Lease.objects.exists()


def test_a_later_step_is_locked_until_the_earlier_one_passes(as_learner, slot, problem):
    lesson = opened(as_learner, problem)

    refused(checked(as_learner, lesson, 2, "right"), 409, "step_locked")
    refused(as_learner.post(f"/api/lessons/{lesson['round']}/steps/3/hint/", {"n": 1}, format="json"), 409,
            "step_locked")
    refused(checked(as_learner, lesson, 9, "right"), 404, "unknown_step")


def test_a_wrong_answer_is_recorded_not_yet_and_a_right_one_passes_and_opens_the_next(as_learner, slot, problem):
    lesson = opened(as_learner, problem)

    wrong = checked(as_learner, lesson, 1, "something else").json()
    right = checked(as_learner, lesson, 1, " Placeholder  Answer ").json()

    assert wrong == {"verdict": "not_yet", "detail_code": "wrong_answer", "next": None}
    assert right == {"verdict": "passed", "detail_code": None, "next": 2}
    assert list(StepResult.objects.filter(round_id=lesson["round"]).values_list("step_order", "verdict")) == [
        (1, "not_yet"), (1, "passed")]
    assert kinds(lesson["round"])[-3:] == ["step.answered", "step.answered", "step.passed"]
    assert checked(as_learner, lesson, 2, "right").json()["verdict"] == "passed"


def test_hints_are_given_one_at_a_time_with_the_count_left(as_learner, slot, problem):
    lesson = opened(as_learner, problem)
    base = f"/api/lessons/{lesson['round']}/steps/1/hint/"

    first = as_learner.post(base, {"n": 1}, format="json").json()
    second = as_learner.post(base, {"n": 2}, format="json").json()

    assert first == {"hint": "first placeholder hint", "n": 1, "left": 1}
    assert second == {"hint": "second placeholder hint", "n": 2, "left": 0}
    refused(as_learner.post(base, {"n": 3}, format="json"), 400, "max_value", path="n")
    refused(as_learner.post(base, {"n": 0}, format="json"), 400, "min_value", path="n")


def test_another_user_neither_reads_nor_answers_someone_else_s_lesson(as_learner, second_browser, slot, problem,
                                                                     make_user, staff):
    lesson = opened(as_learner, problem)
    second_browser.force_authenticate(make_user("stranger"))

    refused(checked(second_browser, lesson, 1, "placeholder answer"), 403, "not_seated")
    refused(second_browser.get(f"/api/lessons/{lesson['round']}/"), 403, "not_seated")
    second_browser.force_authenticate(staff)
    assert second_browser.get(f"/api/lessons/{lesson['round']}/").status_code == 200
    refused(checked(second_browser, lesson, 1, "placeholder answer"), 403, "not_seated")


def test_a_seat_token_does_not_reach_the_lesson_routes(as_learner, second_browser, slot, problem):
    from match import auth

    lesson = opened(as_learner, problem)
    token = auth.issue_token(Seat.objects.get(round_id=lesson["round"], side="defence"))
    second_browser.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    refused(second_browser.get(f"/api/lessons/{lesson['round']}/"), 401, "not_signed_in")
    refused(checked(second_browser, lesson, 1, "placeholder answer"), 401, "not_signed_in")


def test_ending_a_lesson_closes_its_lease_and_a_check_after_it_is_refused(as_learner, slot, problem):
    lesson = opened(as_learner, problem)

    ended = as_learner.post(f"/api/lessons/{lesson['round']}/end/")

    assert ended.status_code == 200 and ended.json()["ended"]
    assert Lease.objects.get(pk=lesson["lease"]).closed is not None
    assert as_learner.get(f"/api/lessons/{lesson['round']}/").json()["phase"] == "ended"
    refused(checked(as_learner, lesson, 1, "placeholder answer"), 409, "round_closed")


def test_my_lessons_list_each_lesson_round_with_the_progress_on_its_problem(as_learner, slot, problem):
    lesson = opened(as_learner, problem)
    checked(as_learner, lesson, 1, "placeholder answer")

    listed = as_learner.get("/api/lessons/?mine=1").json()

    assert listed == [{"round": lesson["round"], "problem": problem.pk, "phase": "ready", "passed_order": 1}]
