import json

import requests

from conftest import PLATFORM_URL
from range import ATTACKER, run

BOARD = "http://board.com"


def _board_session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=120
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _members_from_the_attacker():
    body = run(ATTACKER, ["curl", "-s", "--max-time", "20",
                          f"{BOARD}/members.json"]).stdout
    return {u["username"]: u["password"] for u in json.loads(body)["users"]}


def test_submitting_the_exfiltrated_hashes_credits_the_full_ladder(stack_is_up):
    session_id = _board_session()

    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "board-sqli-search"}, timeout=300,
    )
    assert fired.status_code == 201, fired.text

    loot = _members_from_the_attacker()
    rows = [{"username": name, "hash": digest} for name, digest in loot.items()]
    submitted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/loot/",
        json={"loot": rows}, timeout=120,
    )

    assert submitted.status_code == 200, submitted.text
    assert set(submitted.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert submitted.json()["coverage"] == 1.0


def test_fabricated_loot_is_refused_against_the_live_snapshot(stack_is_up):
    session_id = _board_session()
    requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "board-sqli-search"}, timeout=300,
    )

    submitted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/loot/",
        json={"loot": [{"username": "admin", "password": "admin1234"}]},
        timeout=120,
    )

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["credited"] == []
