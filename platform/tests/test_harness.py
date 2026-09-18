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

    request = build_request(case, BASE)

    assert request["headers"]["X-FSL-Case"] == "abc"
    assert request["url"] == f"{BASE}/rest/products/search"
    assert request["method"] == "GET"


def test_build_request_omits_marker_for_window_cases():
    case = {
        "case_id": "abc",
        "correlation": "window",
        "request": {"method": "GET", "path": "/"},
    }

    request = build_request(case, BASE)

    assert "X-FSL-Case" not in request["headers"]


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

    request = build_request(case, BASE)

    assert request["json"] == {"email": "x", "password": "y"}
    assert request["params"] == {"q": "apple"}


def test_default_cases_file_has_both_labels():
    cases = load_cases(DEFAULT_CASES)

    assert any(c["malicious"] for c in cases), "공격 케이스가 없다"
    assert any(not c["malicious"] for c in cases), (
        "정상 케이스가 없다. 오탐을 채점할 수 없으면 전부 차단하는 룰이 만점을 받는다."
    )


def test_default_cases_declare_a_known_correlation_strategy():
    cases = load_cases(DEFAULT_CASES)

    assert {c["correlation"] for c in cases} <= {"marker", "window"}


def test_default_cases_have_unique_names():
    names = [c["name"] for c in load_cases(DEFAULT_CASES)]

    assert len(names) == len(set(names))


# ── 요청이 선언대로 나갔는지 ─────────────────────────────────────────
#
# requests 는 /ftp/../../../../etc/passwd 를 /etc/passwd 로 정규화해서
# 보낸다. 경로 탐색 공격이 전송되지 않았는데 ground truth 에는 "공격을
# 보냈다" 고 남으면 채점이 거짓말을 한다. 조용히 넘어가서는 안 된다.


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
    # 케이스 파일의 모든 경로가 정규화되지 않고 그대로 나가야 한다.
    import requests

    from redteam.harness import check_path_preserved

    from redteam.tools import is_tool_case

    for case in load_cases(DEFAULT_CASES):
        if is_tool_case(case):
            continue  # 도구 케이스는 requests 를 거치지 않는다
        case = dict(case, case_id="probe")
        spec = build_request(case, BASE)
        prepared = requests.Request(
            method=spec["method"],
            url=spec["url"],
            headers=spec["headers"],
            json=spec["json"],
            params=spec["params"],
        ).prepare()
        check_path_preserved(case["request"]["path"], prepared.url)


def test_case_meta_describes_an_http_case():
    from redteam.harness import case_meta

    case = {"request": {"method": "GET", "path": "/x"}}

    assert case_meta(case) == {"request": {"method": "GET", "path": "/x"}}


def test_case_meta_describes_a_tool_case_without_a_request():
    # 도구 케이스에는 request 가 없다. 여기서 KeyError 가 나면 세션 전체가
    # ground truth 없이 중단된다.
    from redteam.harness import case_meta

    case = {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}

    assert case_meta(case) == {"tool": "sqlmap", "args": ["-u", "{target}/x", "--batch"]}
