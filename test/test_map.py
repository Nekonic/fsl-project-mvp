import pytest
import requests

from conftest import (
    PLATFORM_URL, credited_to, score_when_ready, seen_by_both_engines,
)

CASE = "sqli-login-bypass"
EDGE_COUNTRY = "Russia"

@pytest.fixture(scope="module")
def drawn(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": CASE}, timeout=300,
    )
    assert sent.status_code == 201, sent.text
    case_id = sent.json()["case_id"]
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

                                                                            
                                                                  
    def case_seen_by_both(totals):
        return seen_by_both_engines(session_id, totals, case_id=case_id)

    score = score_when_ready(session_id, until=case_seen_by_both)
    own = {
        d["src_ip"] for d in credited_to(session_id, score, case_id=case_id)
        if d["src_ip"]
    }
    session_map = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
    ).json()
    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    return dict(
        session_map,
        points=[p for p in session_map["points"] if own & set(p["ips"])],
        every_point=session_map["points"],
        listed=listed,
    )

def test_the_attack_is_placed_somewhere(drawn):
    assert drawn["points"], (
        "nothing could be placed on the map. Either the attacker is not on "
        "public space any more or the geoip pipeline is not running"
    )

def test_it_is_placed_where_the_attacker_actually_is(drawn):
    countries = {p["country"] for p in drawn["points"]}

    assert EDGE_COUNTRY in countries, f"placed in {sorted(countries)} instead"

def test_the_point_carries_coordinates_a_map_can_use(drawn):
    point = next(p for p in drawn["points"] if p["country"] == EDGE_COUNTRY)

    assert -90 <= point["lat"] <= 90
    assert -180 <= point["lon"] <= 180
    assert point["detections"] > 0
    assert point["ips"]

def test_traffic_inside_the_estate_is_counted_but_not_placed(drawn):
    placed = {ip for point in drawn["every_point"] for ip in point["ips"]}
    unplaced = [d for d in drawn["listed"] if d["src_ip"] not in placed]

    assert unplaced, (
        "every detection in the session was placed, so nothing here shows "
        "what the map does with traffic it cannot locate. Suricata's alerts "
        "on the inside leg, from the WAF to the target, should be among them"
    )
    assert drawn["unlocated"] == len(unplaced), (
        f"{len(unplaced)} detections come from no placed address and the map "
        f"reports {drawn['unlocated']} unlocated"
    )
    assert sum(p["detections"] for p in drawn["every_point"]) + drawn["unlocated"] == len(
        drawn["listed"]
    ), (
        "the map and the alert list disagree on how many detections the "
        "session holds, so the map dropped or double-counted some"
    )
