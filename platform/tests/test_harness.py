import json
from pathlib import Path

import yaml

from redteam.harness import build_request, load_cases

BASE = "http://localhost:8080"
DEFAULT_CASES = Path(__file__).resolve().parents[2] / "redteam/cases/default.yaml"


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
    # Asserted on the prepared request, so this pins what leaves the process
    # rather than what we intended to send.
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


# -- did the request go out as declared --------------------------------------
#
# requests normalises /ftp/../../../../etc/passwd to /etc/passwd before
# sending. If the traversal never left but ground truth says "attack sent",
# the score lies. That must not pass quietly.


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
    # Every path in the case file must survive preparation unchanged.
    from redteam.harness import check_path_preserved
    from redteam.tools import is_tool_case

    for case in load_cases(DEFAULT_CASES):
        if is_tool_case(case):
            continue  # tool cases never go through requests
        case = dict(case, case_id="probe")
        prepared = build_request(dict(case, case_id="probe"), BASE)
        check_path_preserved(case["request"]["path"], prepared.url)


def test_case_meta_describes_an_http_case():
    from redteam.harness import case_meta

    case = {"request": {"method": "GET", "path": "/x"}}

    assert case_meta(case) == {"request": {"method": "GET", "path": "/x"}}


def test_case_meta_describes_a_tool_case_without_a_request():
    # Tool cases have no request. A KeyError here aborts the whole session with
    # no ground truth at all.
    from redteam.harness import case_meta

    case = {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}

    assert case_meta(case) == {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}
