import time

import pytest
import requests

from conftest import PLATFORM_URL, REPO_ROOT

O_BRIEN = "board-normal-search-with-apostrophe"
EXCLUSION = {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}


def _open(**settings) -> int:
    opened = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board", **settings}, timeout=1800,
    )
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


def _verify(session_id: int) -> dict:
    checked = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/verify/", json={}, timeout=1800)
    assert checked.status_code == 200, checked.text
    return checked.json()


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


def test_the_lesson_starts_with_a_waf_that_blocks_the_o_brien_search(minimal):
    tuning = requests.get(f"{PLATFORM_URL}/api/sessions/{minimal}/waf/", timeout=60).json()
    result = _verify(minimal)

    assert tuning["paranoia"] == 4
    assert result["passed"] is False
    assert [key for key, values in result["diagnosis"] if O_BRIEN in values] == [
        "lesson.diag.benign_blocked"
    ], result["diagnosis"]
    assert all(case["outcome"] == "held" for case in result["cases"] if case["malicious"]), (
        f"paranoia level 4 let an sqlmap variant dump the board's hashes: {result['cases']}"
    )


def test_excluding_one_rule_for_one_parameter_passes_the_lesson(minimal):
    _tune(minimal, {"paranoia": 4, "exclusions": [EXCLUSION]})
    result = _verify(minimal)

    assert result["passed"] is True, result
    assert result["diagnosis"] == [["lesson.diag.blocked_ratio", [2, 2]]]


def test_two_sessions_tune_their_own_waf_and_their_own_sensor(minimal):
    second = minimal
    _tune(second, {"paranoia": 4})
    first = _open(defense="minimal")
    _tune(first, {"paranoia": 1})
    committed = (REPO_ROOT / "deploy/suricata/rules/local.rules").read_text()
    probe = 'alert http any any -> any any (msg:"FSL lesson isolation probe"; sid:9009901; rev:1;)\n'
    applied = requests.post(
        f"{PLATFORM_URL}/api/rules/apply/?session={first}", json={"content": committed + probe},
        timeout=120,
    )

    second_tuning = requests.get(f"{PLATFORM_URL}/api/sessions/{second}/waf/", timeout=60).json()
    first_rules = requests.get(f"{PLATFORM_URL}/api/rules/?session={first}", timeout=60).json()
    second_rules = requests.get(f"{PLATFORM_URL}/api/rules/?session={second}", timeout=60).json()
    served = _fire(first, O_BRIEN)["meta"].get("status")
    refused = _fire(second, O_BRIEN)["meta"].get("status")

    assert applied.status_code == 200, applied.text
    assert first_rules["content"] == committed + probe
    assert second_rules["content"] == committed, "a rule applied in one session reached another's sensor"
    assert second_tuning["paranoia"] == 4, "a tuning applied in one session reached another's record"
    assert (served, refused) == (200, 403), (
        "paranoia level 1 in the first session and 4 in the second should serve and "
        f"block the O'Brien search respectively; got {served} and {refused}"
    )


def test_a_guided_session_opens_with_the_lesson_s_logs_already_there(stack_is_up):
    began = time.monotonic()
    session_id = _open(defense="minimal", guidance=True)
    took = time.monotonic() - began

    cases = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/cases/", timeout=60).json()
    lesson = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/", timeout=60).json()["lesson"]

    assert sorted(case["name"] for case in cases) == sorted(lesson["cases"])
    assert all(case["meta"].get("seed") for case in cases)
    print(f"guided open took {took:.0f} s")
