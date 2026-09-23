import ipaddress

import pytest
import requests

from conftest import (
    PLATFORM_URL, credited_to, score_when_ready, seen_by_both_engines,
)

CASE = "sqli-login-bypass"

@pytest.fixture(scope="module")
def origins(stack_is_up):
    listed = requests.get(f"{PLATFORM_URL}/api/origins/", timeout=120)
    assert listed.status_code == 200, listed.text
    return listed.json()["origins"]

@pytest.fixture(scope="module")
def elsewhere(origins):
    other = [o for o in origins if not o["default"]]
    assert other, "the stack declares only one place to attack from"
    return other[0]

def test_the_stack_offers_more_than_one_place_to_attack_from(origins):
    assert len(origins) >= 2, f"only {[o['id'] for o in origins]}"

def test_each_origin_is_a_different_subnet(origins):
                                                                           
                                                                           
                                                                 
    subnets = [o["subnet"] for o in origins]

    assert len(set(subnets)) == len(subnets), subnets

def test_an_origin_s_address_is_actually_on_its_subnet(origins):
                                                                             
                                                                   
    for origin in origins:
        assert ipaddress.ip_address(origin["source_ip"]) in ipaddress.ip_network(
            origin["subnet"]
        ), f"{origin['id']}: {origin['source_ip']} is not in {origin['subnet']}"

def test_exactly_one_origin_is_the_front_door(origins):
    assert [o["id"] for o in origins if o["default"]].__len__() == 1

@pytest.fixture(scope="module")
def two_places(elsewhere, stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]

    case_ids = {}
    for place, origin in (("front", ""), ("elsewhere", elsewhere["id"])):
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": CASE, "origin": origin}, timeout=300,
        )
        assert sent.status_code == 201, sent.text
        case_ids[place] = sent.json()["case_id"]
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    def both_seen_by_both(totals):
        return all(
            seen_by_both_engines(session_id, totals, case_id=case_id)
            for case_id in case_ids.values()
        )

    score = score_when_ready(session_id, until=both_seen_by_both)
    return {
        "session_id": session_id,
        "sources": {
            place: {
                d["src_ip"] for d in credited_to(session_id, score, case_id=case_id)
                if d["src_ip"]
            }
            for place, case_id in case_ids.items()
        },
        "map": requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
        ).json(),
    }

def test_an_attack_sent_from_elsewhere_arrives_from_elsewhere(two_places, elsewhere):
    subnet = ipaddress.ip_network(elsewhere["subnet"])
    sources = two_places["sources"]["elsewhere"]
    from_there = {ip for ip in sources if ipaddress.ip_address(ip) in subnet}

    assert from_there, (
        f"nothing arrived from {elsewhere['label']} ({subnet}); the alerts came "
        f"from {sorted(sources)}. Either the attack never left by that segment "
        f"or Suricata is not watching the interface it arrived on."
    )

def test_the_two_attacks_did_not_come_from_the_same_address(two_places):
    front = two_places["sources"]["front"]
    there = two_places["sources"]["elsewhere"]

    assert front and there - front, (
        f"the attack sent from elsewhere came from {sorted(there)} and the one "
        f"through the front door from {sorted(front)}"
    )

def test_the_map_draws_more_than_one_place(two_places):
    own = two_places["sources"]["front"] | two_places["sources"]["elsewhere"]
    countries = {
        p["country"] for p in two_places["map"]["points"] if own & set(p["ips"])
    }

    assert len(countries) >= 2, (
        f"the map has one pin - {sorted(countries)} - so either the second "
        f"origin never reached the target or its range geolocates to nothing"
    )

def test_rotation_does_not_stay_in_one_place(stack_is_up, origins):
                                                                           
                                                                            
                                 
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]

    sent = []
    for _ in range(len(origins)):
        response = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": CASE, "origin": "rotate"}, timeout=300,
        )
        assert response.status_code == 201, response.text
        sent.append(response.json()["meta"]["origin"])

    assert set(sent) == {o["id"] for o in origins}, (
        f"{len(origins)} attacks with rotation on used {sorted(set(sent))}"
    )
