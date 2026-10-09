import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

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

def test_load_cases_reads_yaml(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "a",
                    "malicious": True,
                    "correlation": "marker",
                    "request": {"method": "GET", "path": "/"},
                }
            ]
        )
    )

    cases = load_cases(path)

    assert len(cases) == 1
    assert cases[0]["name"] == "a"

def test_build_request_injects_marker_header():
    case = {
        "case_id": "abc",
        "correlation": "marker",
        "request": {"method": "GET", "path": "/rest/products/search"},
    }

    prepared = build_request(case, BASE)

    assert prepared.headers["X-FSL-Case"] == "abc"
    assert prepared.url == f"{BASE}/rest/products/search"
    assert prepared.method == "GET"

def test_build_request_omits_marker_for_window_cases():
    case = {
        "case_id": "abc",
        "correlation": "window",
        "request": {"method": "GET", "path": "/"},
    }

    prepared = build_request(case, BASE)

    assert "X-FSL-Case" not in prepared.headers

def test_build_request_carries_json_body_and_params():
    case = {
        "case_id": "abc",
        "correlation": "marker",
        "request": {
            "method": "POST",
            "path": "/rest/user/login",
            "json": {"email": "x", "password": "y"},
            "params": {"q": "apple"},
        },
    }

    prepared = build_request(case, BASE)

    assert json.loads(prepared.body) == {"email": "x", "password": "y"}
    assert prepared.headers["Content-Type"] == "application/json"
    assert prepared.url.endswith("?q=apple")


def test_build_request_carries_a_form_body():
    case = {
        "case_id": "abc",
        "correlation": "marker",
        "request": {
            "method": "POST",
            "path": "/register/",
            "data": {"user_login": "x", "wp_capabilities[administrator]": "1"},
        },
    }

    prepared = build_request(case, BASE)

    assert prepared.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "wp_capabilities%5Badministrator%5D=1" in prepared.body
    assert "user_login=x" in prepared.body

def test_default_cases_file_has_both_labels():
    cases = load_cases(DEFAULT_CASES)

    assert any(c["malicious"] for c in cases), "no attack cases"
    assert any(not c["malicious"] for c in cases), (
        "no benign cases: without scoring false positives, a block-everything rule wins"
    )

def test_default_cases_declare_a_known_correlation_strategy():
    cases = load_cases(DEFAULT_CASES)

    assert {c["correlation"] for c in cases} <= {"marker", "window"}

def test_default_cases_have_unique_names():
    names = [c["name"] for c in load_cases(DEFAULT_CASES)]

    assert len(names) == len(set(names))


def test_check_path_preserved_accepts_an_unaltered_path():
    from redteam.harness import check_path_preserved

    check_path_preserved("/rest/products/search", "http://h/rest/products/search?q=1")

def test_check_path_preserved_rejects_a_normalized_traversal():
    import pytest

    from redteam.harness import CaseRequestAltered, check_path_preserved

    with pytest.raises(CaseRequestAltered, match="etc/passwd"):
        check_path_preserved("/ftp/../../../../etc/passwd", "http://h/etc/passwd")

def test_check_path_preserved_accepts_percent_encoded_traversal():
    from redteam.harness import check_path_preserved

    path = "/ftp/%2e%2e%2f%2e%2e%2fetc/passwd"
    check_path_preserved(path, f"http://h{path}")

def test_default_cases_survive_request_preparation():
    from redteam.harness import check_path_preserved
    from redteam.tools import is_tool_case

    for case in load_cases(DEFAULT_CASES):
        if is_tool_case(case):
            continue
        case = dict(case, case_id="probe")
        prepared = build_request(dict(case, case_id="probe"), BASE)
        check_path_preserved(case["request"]["path"], prepared.url)

def test_case_meta_describes_an_http_case():
    from redteam.harness import case_meta

    case = {"request": {"method": "GET", "path": "/x"}}

    assert case_meta(case) == {"request": {"method": "GET", "path": "/x"}}

def recorded(case):
    from datetime import datetime, timezone
    from types import SimpleNamespace

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

def test_case_meta_describes_a_tool_case_without_a_request():
    from redteam.harness import case_meta

    case = {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}

    assert case_meta(case) == {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}


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
    assert argv[-1].startswith("http://10.9.0.5/search/"), (
        "the curl must hit the in-range tool target, so the traffic crosses the range"
    )
    assert "board.com" not in argv[-1], "it must not leave for the public target_url"
    assert argv[-1] == build_request(case, "http://10.9.0.5").url, (
        "curl is sent exactly the prepared path, --path-as-is and unaltered"
    )


def test_fire_raises_when_the_request_never_reaches_the_target():
    launch, _ = _launcher(exit_code=7, output="curl: (7) Failed to connect")
    case = {
        "case_id": "c", "name": "board-sqli-search", "correlation": "marker",
        "request": {"method": "GET", "path": "/search/"},
    }

    with pytest.raises(harness.ToolUnavailable):
        harness.fire(case, launch, "http://10.9.0.5")


def test_run_does_not_record_a_case_whose_request_never_landed(monkeypatch):
    recorded = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": 7}

    class Http:
        def post(self, url, json=None, timeout=None):
            return Resp()

    monkeypatch.setattr(harness.requests, "Session", lambda: Http())
    monkeypatch.setattr(
        harness, "fire",
        lambda *a, **k: (_ for _ in ()).throw(harness.ToolUnavailable("never landed")),
    )
    monkeypatch.setattr(harness, "_record", lambda *a, **k: recorded.append(1))

    with pytest.raises(harness.ToolUnavailable):
        harness.run(
            [{"name": "a", "malicious": True, "request": {"path": "/search/"}}],
            "http://p", lambda *a, **k: None,
        )
    assert recorded == [], "a case that never reached the target must not be recorded as fired"


def test_run_opens_a_session_fires_each_case_then_closes(monkeypatch):
    posts = []
    bodies = []

    class Resp:
        def __init__(self, body=None):
            self._body = body or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    class Http:
        def post(self, url, json=None, timeout=None):
            posts.append(url)
            bodies.append(json)
            return Resp({"id": 7} if url.endswith("/api/sessions/") else {})

    fired, recorded = [], []
    monkeypatch.setattr(harness.requests, "Session", lambda: Http())
    monkeypatch.setattr(harness, "fire", lambda case, *a, **k: fired.append(case["name"]))
    monkeypatch.setattr(
        harness, "_record",
        lambda http, url, sid, case, *a, **k: recorded.append((sid, case["name"])),
    )

    cases = [{"name": "a", "request": {"path": "/"}},
             {"name": "b", "request": {"path": "/"}}]
    session_id = harness.run(cases, "http://p", lambda *a, **k: None)

    assert session_id == 7
    assert fired == ["a", "b"]
    assert recorded == [(7, "a"), (7, "b")]
    assert posts[0].endswith("/api/sessions/")
    assert posts[-1].endswith("/api/sessions/7/close/")
    assert bodies[0] == {"scenario": "board"}

    bodies.clear()
    harness.run(cases, "http://p", lambda *a, **k: None, scenario="corp")
    assert bodies[0] == {"scenario": "corp"}


def test_opening_a_session_waits_as_long_as_its_stack_takes_to_come_up(monkeypatch):
    waited = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": 7}

    class Http:
        def post(self, url, json=None, timeout=None):
            waited.setdefault(url, timeout)
            return Resp()

    monkeypatch.setattr(harness.requests, "Session", lambda: Http())

    harness.run([], "http://p", lambda *a, **k: None)

    assert waited["http://p/api/sessions/"] >= 300, (
        "opening a session starts its compose stack and waits for the target "
        "to be healthy, about 40 s on the test range; a 15 s request gives up "
        "while the stack is still coming up"
    )
