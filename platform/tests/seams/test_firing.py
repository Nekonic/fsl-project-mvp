from pathlib import Path
from types import SimpleNamespace

import pytest

from attack import firing as harness
from attack.firing import build_request, load_cases

def _launcher(exit_code=0, output="200"):
    calls = []

    def launch(argv, timeout=None):
        calls.append(argv)
        return SimpleNamespace(exit_code=exit_code, output=output)

    return launch, calls

BASE = "http://localhost:8080"
DEFAULT_CASES = Path(__file__).resolve().parents[3] / "redteam/cases/board.yaml"

def test_build_request_omits_marker_for_window_cases():
    case = {
        "case_id": "abc",
        "correlation": "window",
        "request": {"method": "GET", "path": "/"},
    }

    prepared = build_request(case, BASE)

    assert "X-Request-ID" not in prepared.headers

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
    from attack.firing import check_path_preserved
    from attack.tools import is_tool_case

    for case in load_cases(DEFAULT_CASES):
        if is_tool_case(case):
            continue
        case = dict(case, case_id="probe")
        prepared = build_request(dict(case, case_id="probe"), BASE)
        check_path_preserved(case["request"]["path"], prepared.url)

def test_fire_refuses_to_send_a_case_whose_path_was_altered(monkeypatch):
    launch, launched = _launcher()

    class Prepared:
        url = "http://board.com/y"
        method = "GET"
        headers: dict = {}
        body = None

    monkeypatch.setattr(harness, "build_request", lambda case, base, marker=None: Prepared())
    case = {
        "case_id": "c", "name": "n", "correlation": "marker",
        "request": {"method": "GET", "path": "/x/../y"},
    }

    with pytest.raises(harness.CaseRequestAltered):
        harness.fire(case, launch, BASE)
    assert launched == [], "a case whose path changed must never reach the attacker box"


def test_fire_launches_an_http_case_as_curl_on_the_attacker_box():
    launch, launched = _launcher()
    case = {
        "case_id": "abc", "name": "board-sqli-search", "correlation": "marker",
        "request": {"method": "GET", "path": "/search/", "params": {"q": "' OR 1=1--"}},
    }

    harness.fire(case, launch, "http://10.9.0.5")

    assert len(launched) == 1, "an HTTP case must fire through the attacker-box launcher"
    argv = launched[0]
    assert argv[0] == "curl"
    assert "--path-as-is" in argv
    assert "X-Request-ID: abc" in argv, "the marker the proxy labels the request by must be sent"
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


BENIGN_KEPT = {
    "board.yaml": {
        "board-normal-search", "board-normal-search-with-apostrophe", "board-normal-post-list",
        "board-normal-sort", "board-normal-search-korean", "board-normal-comment",
    },
    "corp.yaml": {
        "corp-normal-home", "corp-normal-registration-page", "corp-normal-search", "corp-normal-registration",
    },
}

def test_every_case_file_keeps_its_benign_cases():
    files = sorted(DEFAULT_CASES.parent.glob("*.yaml"))

    assert sorted(path.name for path in files) == sorted(BENIGN_KEPT), (
        "a case file without a committed list of its benign cases can lose them unseen")
    for path in files:
        benign = {case["name"] for case in load_cases(path) if not case["malicious"]}
        assert benign, f"{path.name} has no benign case, so a rule set that blocks everything scores perfectly"
        assert BENIGN_KEPT[path.name] <= benign, (
            f"{path.name} lost the benign cases {sorted(BENIGN_KEPT[path.name] - benign)}; "
            f"removing one makes the score look better and the platform pointless")


def test_the_comment_cases_post_the_form_with_the_cookie_and_the_token_the_form_page_gave():
    page = ("HTTP/1.1 200 OK\r\nSet-Cookie: csrftoken=Cookie64; Path=/; SameSite=Lax\r\n\r\n"
            '<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="Masked64"></form>')
    cases = {case["name"]: case for case in harness.load_cases(DEFAULT_CASES)}
    for name in ("board-xss-img-onerror-in-comment", "board-normal-comment"):
        launch, launched = _launcher(output=page)
        harness.fire(dict(cases[name], case_id="c"), launch, "http://board.com")

        fetched, posted = launched
        assert "-i" in fetched and fetched[-1] == "http://board.com/posts/1/", "the form page's Set-Cookie is read"
        assert not [part for part in fetched if "{" in part], "no placeholder goes out on the form page's GET"
        assert "Cookie: csrftoken=Cookie64" in posted
        body = posted[posted.index("--data-binary") + 1]
        assert body.startswith("csrfmiddlewaretoken=Masked64&body="), (
            "the board refuses a comment without the form's CSRF token 403, so the attack would never land")
        assert "Content-Type: application/x-www-form-urlencoded" in posted, "the comment view reads request.POST"


def test_an_api_send_carries_the_marker_the_platform_chose_not_the_case_id():
    case = {"case_id": "abc", "correlation": "window", "request": {"method": "GET", "path": "/"}}

    assert build_request(case, BASE, marker="action-17").headers["X-Request-ID"] == "action-17"
