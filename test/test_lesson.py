import ipaddress

import pytest
import requests

from conftest import PLATFORM_URL, REPO_ROOT

O_BRIEN = "board-normal-search-with-apostrophe"


def _open(**settings) -> int:
    opened = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board", **settings}, timeout=1800,
    )
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


def _tune(session_id: int, tuning: dict) -> dict:
    put = requests.put(f"{PLATFORM_URL}/api/sessions/{session_id}/waf/", json=tuning, timeout=120)
    assert put.status_code == 200, put.text
    return put.json()


def _fire(session_id: int, case: str) -> dict:
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/", json={"case": case}, timeout=900,
    )
    assert sent.status_code == 201, sent.text
    return sent.json()


@pytest.fixture(scope="module")
def minimal(stack_is_up):
    return _open(defense="minimal")


@pytest.fixture(scope="module")
def guided_beside_minimal(minimal):
    first = _open(defense="minimal", guidance=True, lesson="f1")
    seen = {}
    try:
        second = minimal
        _tune(second, {"paranoia": 4})
        _tune(first, {"paranoia": 1})
        committed = (REPO_ROOT / "deploy/suricata/rules/local.rules").read_text()
        probe = 'alert http any any -> any any (msg:"lesson isolation probe"; sid:9009901; rev:1;)\n'
        seen["committed"], seen["probe"] = committed, probe
        seen["applied"] = requests.post(
            f"{PLATFORM_URL}/api/rules/apply/?session={first}", json={"content": committed + probe},
            timeout=120,
        )

        seen["second_tuning"] = requests.get(f"{PLATFORM_URL}/api/sessions/{second}/waf/", timeout=60).json()
        seen["first_rules"] = requests.get(f"{PLATFORM_URL}/api/rules/?session={first}", timeout=60).json()
        seen["second_rules"] = requests.get(f"{PLATFORM_URL}/api/rules/?session={second}", timeout=60).json()
        seen["served"] = _fire(first, O_BRIEN)["meta"].get("status")
        seen["refused"] = _fire(second, O_BRIEN)["meta"].get("status")
    finally:
        requests.post(f"{PLATFORM_URL}/api/sessions/{first}/close/", json={}, timeout=120)
    return seen


def test_two_sessions_tune_their_own_waf_and_their_own_sensor(guided_beside_minimal):
    seen = guided_beside_minimal
    committed, probe, applied = seen["committed"], seen["probe"], seen["applied"]
    served, refused = seen["served"], seen["refused"]

    assert applied.status_code == 200, applied.text
    assert seen["first_rules"]["content"] == committed + probe
    assert seen["second_rules"]["content"] == committed, "a rule applied in one session reached another's sensor"
    assert seen["second_tuning"]["paranoia"] == 4, "a tuning applied in one session reached another's record"
    assert (served, refused) == (200, 403), (
        "paranoia level 1 in the first session and 4 in the second should serve and "
        f"block the O'Brien search respectively; got {served} and {refused}"
    )


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
    route = ["kali", *(["firewall"] if "firewall" in hosts else []), "waf", "board.com"]
    board = _drawn_address(listed, project, "board.com", "sw1")
    given = {
        "kali_ip": _drawn_address(listed, project, "kali", "internet").partition("/")[0],
        "board_ip": board.partition("/")[0],
        "path": " > ".join(route),
        "dmz": str(ipaddress.ip_interface(board).network),
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
