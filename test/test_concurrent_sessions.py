import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

CASE = "board-sqli-search"


def _open() -> int:
    opened = requests.post(f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=900)
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


@pytest.fixture(scope="module")
def two_sessions(stack_is_up):
    first, second = _open(), _open()
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{first}/attacks/", json={"case": CASE}, timeout=300,
    )
    assert sent.status_code == 201, sent.text

    def case_detected(totals):
        return any(c["name"] == CASE and c["detected"] for c in totals["per_case"])

    score_when_ready(first, until=case_detected)
    requests.post(f"{PLATFORM_URL}/api/sessions/{second}/ingest/", timeout=120)
    yield first, second, sent.json()["case_id"]
    for session_id in (first, second):
        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)


def test_both_sessions_stay_open_at_once(two_sessions):
    first, second, _ = two_sessions
    open_ids = {row["id"] for row in requests.get(
        f"{PLATFORM_URL}/api/sessions/?state=open", timeout=30
    ).json()}

    assert {first, second} <= open_ids, (
        "opening the second session closed the first or took its stack down"
    )


def test_an_attack_on_one_session_draws_no_alert_in_the_other(two_sessions):
    first, second, marker = two_sessions
    seen = requests.get(f"{PLATFORM_URL}/api/sessions/{second}/detections/", timeout=120).json()

    assert not [d for d in seen if d["marker"] == marker], (
        f"session {second} scored alerts drawn by session {first}'s attack: its "
        f"index or its sensor is shared"
    )
    assert not requests.get(
        f"{PLATFORM_URL}/api/sessions/{second}/cases/", timeout=60
    ).json(), f"session {first}'s case was recorded on session {second}"
