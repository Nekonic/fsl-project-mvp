import pytest
import requests

from conftest import PLATFORM_URL, REPO_ROOT, score_when_ready

CASE = "board-sqli-search"
O_BRIEN = "board-normal-search-with-apostrophe"


def _open(**settings) -> int:
    opened = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board", **settings}, timeout=1800,
    )
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


@pytest.fixture(scope="module")
def two_sessions(stack_is_up):
    opened = [_open()]
    try:
        opened.append(_open())
        first, second = opened
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{first}/attacks/", json={"case": CASE}, timeout=300,
        )
        assert sent.status_code == 201, sent.text

        def case_detected(totals):
            return any(c["name"] == CASE and c["detected"] for c in totals["per_case"])

        score_when_ready(first, until=case_detected)
        requests.post(f"{PLATFORM_URL}/api/sessions/{second}/ingest/", timeout=120)
        seen = {
            "first": first, "second": second, "marker": sent.json()["case_id"],
            "open": {row["id"] for row in requests.get(
                f"{PLATFORM_URL}/api/sessions/?state=open", timeout=30
            ).json()},
            "second_detections": requests.get(
                f"{PLATFORM_URL}/api/sessions/{second}/detections/", timeout=120
            ).json(),
            "second_cases": requests.get(f"{PLATFORM_URL}/api/sessions/{second}/cases/", timeout=60).json(),
        }
    finally:
        for session_id in opened:
            requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)
    return seen


def test_both_sessions_stay_open_at_once(two_sessions):
    first, second = two_sessions["first"], two_sessions["second"]

    assert {first, second} <= two_sessions["open"], (
        "opening the second session closed the first or took its stack down"
    )


def test_an_attack_on_one_session_draws_no_alert_in_the_other(two_sessions):
    first, second, marker = two_sessions["first"], two_sessions["second"], two_sessions["marker"]

    assert not [d for d in two_sessions["second_detections"] if d["marker"] == marker], (
        f"session {second} scored alerts drawn by session {first}'s attack: its "
        f"index or its sensor is shared"
    )
    assert not two_sessions["second_cases"], f"session {first}'s case was recorded on session {second}"


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
        for session_id in (first, minimal):
            requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)
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
