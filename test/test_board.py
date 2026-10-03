import requests

from conftest import PLATFORM_URL, score_when_ready


def _board_session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=120
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _fire(session_id, case):
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": case}, timeout=300,
    )
    assert fired.status_code == 201, fired.text
    return fired.json()["case_id"]


def test_an_attack_on_the_board_is_detected_and_a_benign_request_passes(stack_is_up):
    session_id = _board_session()
    attack = _fire(session_id, "board-sqli-search")
    benign = _fire(session_id, "board-normal-search")

    def attack_detected(totals):
        return any(c["case_id"] == attack and c["detected"] for c in totals["per_case"])

    score = score_when_ready(session_id, until=attack_detected)

    attacked = next(c for c in score["per_case"] if c["case_id"] == attack)
    assert attacked["detected"], f"the board SQLi raised no alert: {score}"
    assert attacked["corroborated"], (
        f"the alert did not mention the attack's own mechanism: {attacked}"
    )

    passed = next((c for c in score["per_case"] if c["case_id"] == benign), None)
    assert passed is not None and not passed["detected"], (
        f"an ordinary board search raised an alert: {passed}"
    )

    assert score["tp"] > 0 and score["tn"] > 0, score


def test_a_board_session_lists_its_loot_tiers_and_starts_with_none_taken(stack_is_up):
    tiers = requests.get(
        f"{PLATFORM_URL}/api/wargames/board/objectives/", timeout=60
    ).json()
    assert {t["key"] for t in tiers} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }

    session_id = _board_session()
    observed = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
    )
    assert observed.status_code == 200, observed.text
    assert observed.json() == {"achieved": 0, "total": 0}, observed.json()
