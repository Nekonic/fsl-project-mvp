import time

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
    began = time.monotonic()
    first = _open(defense="minimal", guidance=True, lesson="f1")
    seen = {"took": time.monotonic() - began}
    try:
        seen["cases"] = requests.get(f"{PLATFORM_URL}/api/sessions/{first}/cases/", timeout=60).json()
        seen["lesson"] = requests.get(f"{PLATFORM_URL}/api/sessions/{first}/", timeout=60).json()["lesson"]

        second = minimal
        _tune(second, {"paranoia": 4})
        _tune(first, {"paranoia": 1})
        committed = (REPO_ROOT / "deploy/suricata/rules/local.rules").read_text()
        probe = 'alert http any any -> any any (msg:"FSL lesson isolation probe"; sid:9009901; rev:1;)\n'
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


def test_a_foundation_session_opens_with_its_logs_already_there(guided_beside_minimal):
    cases = guided_beside_minimal["cases"]
    lesson = guided_beside_minimal["lesson"]

    assert lesson["id"] == "f1"
    assert sorted(case["name"] for case in cases) == sorted(lesson["cases"])
    assert all(case["meta"].get("seed") for case in cases)
    print(f"guided open took {guided_beside_minimal['took']:.0f} s")
