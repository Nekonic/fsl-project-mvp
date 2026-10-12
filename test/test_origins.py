import ipaddress

import pytest

@pytest.fixture(scope="module")
def origins(origins_session):
    return origins_session["origins"]

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
def two_places(origins_session, elsewhere):
    return origins_session

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

def test_rotation_does_not_stay_in_one_place(origins_session, origins):
    sent = []
    for response in origins_session["rotated"]:
        assert response.status_code == 201, response.text
        sent.append(response.json()["meta"]["origin"])

    assert set(sent) == {o["id"] for o in origins}, (
        f"{len(origins)} attacks with rotation on used {sorted(set(sent))}"
    )
