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
