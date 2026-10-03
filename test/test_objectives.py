import json

import requests

from conftest import PLATFORM_URL, score_when_ready
from range import SCORER, run

EXFIL_CASE = "board-sqli-search"


def _auth_users_over_estate():
    body = run(SCORER, [
        "python3", "-c",
        "import urllib.request,sys; "
        "sys.stdout.write(urllib.request.urlopen("
        "'http://board:8000/internal/auth-users', timeout=20).read().decode())",
    ]).stdout
    return json.loads(body)


def test_a_breach_is_scored_and_attributed_to_the_attack_that_took_it(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=120
    ).json()["id"]

    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": EXFIL_CASE}, timeout=300,
    )
    assert fired.status_code == 201, fired.text
    case_id = fired.json()["case_id"]

    truth = _auth_users_over_estate()
    rows = [{"username": name, "hash": digest} for name, digest in truth.items()]
    submitted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/loot/",
        json={"loot": rows, "case_id": case_id}, timeout=120,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["credited"], "the exfiltrated hashes credited no tier"

    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    def fired_case(totals):
        return next((c for c in totals["per_case"] if c["case_id"] == case_id), {})

    scored = score_when_ready(
        session_id, until=lambda t: bool(fired_case(t).get("detection_ids"))
    )
    own = fired_case(scored)

    assert own.get("detection_ids"), (
        f"the attack that took the loot (case {case_id}) drew no detection, so a "
        f"breach credited to it reads exactly like one credited to nothing"
    )
    assert scored["breaches"], "nothing was taken, so attribution proves nothing"
    for breach in scored["breaches"]:
        assert (breach["detected"], sorted(breach["detection_ids"])) == (
            own["detected"], sorted(own["detection_ids"])
        ), (
            f"the loot was windowed to case {case_id}, so each breach must carry "
            f"that case's detections; {breach['key']} carried something else"
        )
