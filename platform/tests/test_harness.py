from pathlib import Path
from types import SimpleNamespace

import pytest

from redteam import harness
from redteam.harness import build_request, load_cases
from redteam.tools import TOOL_IMAGE

def _launcher(exit_code=0, output="200"):
    calls = []

    def launch(image, argv, timeout=None):
        calls.append((image, argv))
        return SimpleNamespace(exit_code=exit_code, output=output)

    return launch, calls

BASE = "http://localhost:8080"
DEFAULT_CASES = Path(__file__).resolve().parents[2] / "redteam/cases/board.yaml"

def test_build_request_omits_marker_for_window_cases():
    case = {
        "case_id": "abc",
        "correlation": "window",
        "request": {"method": "GET", "path": "/"},
    }

    prepared = build_request(case, BASE)

    assert "X-FSL-Case" not in prepared.headers

def test_default_cases_file_has_both_labels_known_correlations_and_unique_names():
    cases = load_cases(DEFAULT_CASES)
    names = [c["name"] for c in cases]

    assert any(c["malicious"] for c in cases), "no attack cases"
    assert any(not c["malicious"] for c in cases), (
        "no benign cases: without scoring false positives, a block-everything rule wins"
    )
    assert {c["correlation"] for c in cases} <= {"marker", "window"}
    assert len(names) == len(set(names))

def test_default_cases_survive_request_preparation():
    from redteam.harness import check_path_preserved
    from redteam.tools import is_tool_case

    for case in load_cases(DEFAULT_CASES):
        if is_tool_case(case):
            continue
        case = dict(case, case_id="probe")
        prepared = build_request(dict(case, case_id="probe"), BASE)
        check_path_preserved(case["request"]["path"], prepared.url)

def recorded(case):
    from datetime import datetime, timezone

    from redteam.harness import _record

    posted = []

    class Platform:
        def post(self, url, json, timeout):
            posted.append(json)
            return SimpleNamespace(raise_for_status=lambda: None)

    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    _record(Platform(), "http://platform", 1, dict(
        {"case_id": "c", "name": "n", "correlation": "marker",
         "request": {"method": "GET", "path": "/"}},
        **case,
    ), now, now)
    return posted[0]

def test_the_harness_records_whether_a_case_is_an_attack_as_the_file_says_it():
    assert recorded({"malicious": "false"})["malicious"] == "false", (
        "the harness turned the string \"false\" into True before the platform "
        "could refuse it: a benign case typed wrongly was recorded as an attack"
    )

def test_the_harness_records_what_the_case_was_to_be_found_by():
    posted = recorded({
        "malicious": True, "stage": "exploitation", "technique": "T1190",
        "pattern": "CAPEC-66", "expect": "SQL",
    })

    assert {field: posted.get(field) for field in ("stage", "technique", "pattern", "expect")} == {
        "stage": "exploitation", "technique": "T1190",
        "pattern": "CAPEC-66", "expect": "SQL",
    }, (
        "a case fired by the harness was scored against whatever the case file "
        "said at scoring time, not what it said when the attack ran"
    )


def test_fire_refuses_to_send_a_case_whose_path_was_altered(monkeypatch):
    launch, launched = _launcher()

    class Prepared:
        url = "http://board.com/y"
        method = "GET"
        headers: dict = {}
        body = None

    monkeypatch.setattr(harness, "build_request", lambda case, base: Prepared())
    case = {
        "case_id": "c", "name": "n", "correlation": "marker",
        "request": {"method": "GET", "path": "/x/../y"},
    }

    with pytest.raises(harness.CaseRequestAltered):
        harness.fire(case, launch)
    assert launched == [], "a case whose path changed must never reach the attacker box"


def test_fire_launches_an_http_case_as_curl_on_the_attacker_box():
    launch, launched = _launcher()
    case = {
        "case_id": "abc", "name": "board-sqli-search", "correlation": "marker",
        "request": {"method": "GET", "path": "/search/", "params": {"q": "' OR 1=1--"}},
    }

    harness.fire(case, launch, "http://10.9.0.5")

    assert len(launched) == 1, "an HTTP case must fire through the attacker-box launcher"
    image, argv = launched[0]
    assert image == TOOL_IMAGE, "it runs the same image tool cases use (the Kali box)"
    assert argv[0] == "curl"
    assert "--path-as-is" in argv
    assert "X-FSL-Case: abc" in argv, "the marker the proxy labels the request by must be sent"
    assert argv[-1] == build_request(case, "http://10.9.0.5").url, (
        "curl is sent exactly the prepared path to the in-range tool target, unaltered"
    )


@pytest.mark.parametrize("exit_code, output, request_", [
    (7, "curl: (7) Failed to connect", {"method": "GET", "path": "/search/"}),
    (0, "no token on this page", {"method": "GET", "path": "/a",
                                  "prefetch": {"from": "/form", "pattern": r'"nonce":"([a-f0-9]+)"'}}),
])
def test_fire_raises_when_the_request_never_reaches_the_target_as_the_case_built_it(exit_code, output, request_):
    launch, _ = _launcher(exit_code=exit_code, output=output)
    case = {"case_id": "c", "name": "n", "correlation": "marker", "request": request_}

    with pytest.raises(harness.ToolUnavailable):
        harness.fire(case, launch, "http://10.9.0.5")


def test_run_opens_a_session_of_its_scenario_records_each_case_in_it_then_closes(monkeypatch):
    posts, bodies, fired, recorded = [], [], [], []

    class Resp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    class Http:
        def post(self, url, json=None, timeout=None):
            posts.append(url)
            bodies.append(json)
            return Resp({"id": 7} if url.endswith("/api/sessions/") else {})

    monkeypatch.setattr(harness.requests, "Session", lambda: Http())
    monkeypatch.setattr(harness, "fire", lambda case, *a, **k: fired.append(case["name"]))
    monkeypatch.setattr(
        harness, "_record",
        lambda http, url, sid, case, *a, **k: recorded.append((sid, case["name"])),
    )

    cases = [{"name": "a", "request": {"path": "/"}}, {"name": "b", "request": {"path": "/"}}]

    assert harness.run(cases, "http://p", lambda *a, **k: None, scenario="corp") == 7
    assert bodies[0] == {"scenario": "corp"}
    assert fired == ["a", "b"] and recorded == [(7, "a"), (7, "b")]
    assert posts[-1].endswith("/api/sessions/7/close/")

def test_a_run_that_fails_midway_still_closes_its_session_and_said_which_it_was(monkeypatch):
    posts, announced = [], []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": 9}

    class Http:
        def post(self, url, json=None, timeout=None):
            posts.append(url)
            return Resp()

    monkeypatch.setattr(harness.requests, "Session", lambda: Http())
    monkeypatch.setattr(
        harness, "fire",
        lambda *a, **k: (_ for _ in ()).throw(harness.ToolUnavailable("tool died")),
    )

    with pytest.raises(harness.ToolUnavailable):
        harness.run(
            [{"name": "a", "malicious": True, "request": {"path": "/"}}],
            "http://p", lambda *a, **k: None, announce=announced.append,
        )

    assert announced == [9], "the caller could not tell which session the run opened"
    assert posts[-1].endswith("/api/sessions/9/close/"), (
        "a run that failed midway left its session open, holding a place under the cap"
    )
