import requests

from conftest import PLATFORM_URL


def test_the_score_is_withheld_while_the_session_is_open_and_shown_once_closed(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=120
    ).json()["id"]

    while_open = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60)
    assert while_open.status_code == 200, while_open.text
    assert while_open.json()["game"] == {"revealed": False}, (
        "the game score leaked before the session closed; a live tally lets "
        "either side play to the number"
    )

    closed = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)
    assert closed.status_code == 200, closed.text

    after = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60).json()
    assert after["game"]["revealed"] is True, after["game"]
    for pillar in ("speed", "accuracy", "coverage", "balance"):
        assert pillar in after["game"], after["game"]
