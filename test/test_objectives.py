import uuid
from datetime import datetime, timezone

import pytest
import requests

from conftest import PLATFORM_URL, from_attacker, reset_target

                                                                             
                                                                            
                                                                             
                                                                           
                                               
                                                                              
                                                                       
                                                                         
                                                                            
                                                                              
                                                                             
REACHABLE = [
    ("forgottenBackupChallenge", "/ftp/coupons_2013.md.bak%2500.md"),
]

def _now():
    return datetime.now(timezone.utc)

@pytest.fixture(scope="module")
def unsolved(stack_is_up):
    catalogue = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    solved = {o["key"] for o in catalogue if o["solved"]}

    for key, path in REACHABLE:
        if key not in solved:
            return key, path

                                                                             
                                                                      
                                             
    reset_target()

    catalogue = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    solved = {o["key"] for o in catalogue if o["solved"]}
    for key, path in REACHABLE:
        if key not in solved:
            return key, path

    raise AssertionError(
        "the target was reset and still reports these objectives as solved: "
        f"{sorted(solved)}"
    )

@pytest.fixture(scope="module")
def breach_session(unsolved):
    key, path = unsolved
    source_ip = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60).json()["source_ip"]
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=60
    ).json()["id"]

    case_id = str(uuid.uuid4())
    requests.post(f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": case_id}, timeout=30)
    try:
        started = _now()
        from_attacker(path)
        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60)
    finally:
        requests.post(f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": None}, timeout=30)

    requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": case_id, "name": "terminal-objective", "malicious": True,
            "correlation": "window", "source_ip": source_ip,
            "started_at": started.isoformat(), "ended_at": _now().isoformat(),
        },
        timeout=30,
    )
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=30)
    return session_id, key

def test_the_target_decides_an_objective_was_taken(breach_session):
    session_id, key = breach_session

    taken = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=30
    ).json()

                                                                             
                                                                              
                                                                            
                                                                              
                                                                       
    keys = [o["key"] for o in taken]
    assert key in keys, keys
    assert all(o["difficulty"] >= 1 for o in taken)

def test_objectives_solved_before_the_session_are_not_counted(breach_session):
                                                                           
                                                                     
    session_id, _ = breach_session
    fresh = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=60).json()["id"]

    requests.post(f"{PLATFORM_URL}/api/sessions/{fresh}/objectives/", timeout=60)

    assert requests.get(
        f"{PLATFORM_URL}/api/sessions/{fresh}/objectives/", timeout=30
    ).json() == []

def test_a_breach_is_scored_and_attributed_to_the_attack_that_took_it(breach_session):
    session_id, key = breach_session
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/", timeout=180)

    scored = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60).json()

    assert scored["objectives"]["objectives"] >= 1
    breach = next(b for b in scored["breaches"] if b["key"] == key)
                                                                              
                                                                             
                                
    assert breach["difficulty"] >= 1
    assert breach["detected"] is (len(breach["detection_ids"]) > 0)

                                                                           
                                          
    seen = [b["detected"] for b in scored["breaches"]]
    if all(seen) or not any(seen):
        assert scored["objectives"]["coverage"] == (1.0 if seen[0] else 0.0)
