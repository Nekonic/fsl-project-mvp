
import pytest
import requests

from conftest import PLATFORM_URL


def _open(**settings) -> int:
    opened = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board", **settings}, timeout=1800,
    )
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


def _post(path: str, body: dict, timeout: float = 120):
    return requests.post(f"{PLATFORM_URL}/api/sessions/{path}", json=body, timeout=timeout)


def _walked(session_id: int) -> dict:
    seen = {"checked": [], "refused": []}
    detail = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/", timeout=60).json()
    while True:
        lesson_id = detail["lesson_id"]
        for shown in detail["lesson"]["steps"]:
            step = shown["id"]
            _post(f"{session_id}/lesson/steps/{step}/", {"state": "reached"})
            body = {"answer": "x"} if shown["check"]["kind"] in ("answer", "choice") else {"poll": True}
            checked = _post(f"{session_id}/lesson/steps/{step}/check/", body, timeout=300)
            seen["checked"].append((lesson_id, step, checked.status_code))
            if checked.status_code != 200:
                seen["refused"].append((lesson_id, step, checked.status_code, checked.text[:200]))
            _post(f"{session_id}/lesson/steps/{step}/", {"state": "skipped"})
        if not detail["next_lesson"]:
            return seen
        moved = _post(f"{session_id}/lesson/", {"lesson": detail["next_lesson"]["id"]}, timeout=900)
        assert moved.status_code == 200, moved.text
        detail = moved.json()


def _courses() -> dict:
    board = next(wargame for wargame in requests.get(f"{PLATFORM_URL}/api/wargames/", timeout=60).json()
                 if wargame["id"] == "board")
    return {course["id"]: course["lessons"] for course in board["courses"]}


def _drawn_address(listed: list, project: dict, host: str, switch: str) -> str:
    on = {address.partition("/")[0]: address for address in project["nodes"][host]["addresses"].get(switch, [])}
    return next(on[row["address"]] for row in listed if row["host"] == host and row["address"] in on)


def _map_answers(session_id: int) -> dict:
    project = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=120).json()["project"]
    listed = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/lesson/addresses/", timeout=120).json()["addresses"]
    steps = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/", timeout=60).json()["lesson"]["steps"]
    hosts = next(step["check"]["options"] for step in steps if step["id"] == "path")
    route = ["customers", *(["router"] if "router" in hosts else []), "waf", "board.com"]
    board = _drawn_address(listed, project, "board.com", "sw1")
    given = {
        "kali_ip": _drawn_address(listed, project, "kali", "internet").partition("/")[0],
        "board_ip": board.partition("/")[0],
        "path": " > ".join(route),
        "dmz": next(row["network"] for row in listed if row["host"] == "board.com" and row["network"]),
        "log_host": "log-server",
        "waf_ip": _drawn_address(listed, project, "waf", "sw1").partition("/")[0],
    }
    assert set(given) == {step["id"] for step in steps}, "F1's steps changed; this test answers each one"
    return {step: _post(f"{session_id}/lesson/steps/{step}/check/", {"answer": answer}).json()["passed"]
            for step, answer in given.items()}


@pytest.fixture(scope="module", params=["c1", "c2"])
def course(request, stack_is_up):
    lessons = _courses()[request.param]
    session_id = _open(guidance=True, lesson=lessons[0])
    seen = {"id": request.param, "lessons": lessons}
    try:
        seen["course"] = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/", timeout=60).json()["lesson_course"]
        if lessons[0] == "f1":
            seen["map"] = _map_answers(session_id)
        seen.update(_walked(session_id))
    finally:
        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)
    seen["score"] = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=300).json()
    return seen


def test_f1_reads_its_answers_from_the_map_of_the_session_s_own_range(course):
    if "map" not in course:
        pytest.skip(f"course {course['id']} does not start with F1")
    assert course["map"] == {step: True for step in ("kali_ip", "board_ip", "path", "dmz", "log_host", "waf_ip")}


def test_each_course_runs_its_lessons_in_one_session_and_every_step_s_check_answers(course):
    assert course["course"]["id"] == course["id"] and course["course"]["lessons"] == course["lessons"]
    assert course["refused"] == []
    assert [lesson for lesson in dict.fromkeys(lesson for lesson, _, _ in course["checked"])] == course["lessons"]


def test_the_two_courses_teach_the_six_foundations_once_each(stack_is_up):
    assert sorted(lesson for lessons in _courses().values() for lesson in lessons) == ["f1", "f2", "f3", "f4", "f5", "f6"]


def test_a_closed_course_scores_each_lesson_s_seed_as_a_benign_case_and_warns_no_operator(course):
    score = course["score"]
    assert score["benign_cases"] == len(course["lessons"]), "one seed replay per lesson, each a benign case of the second score"
    assert not [warning for warning in score["warnings"]
                if warning[0] in ("score.warning.no_benign", "score.warning.no_marker")]
