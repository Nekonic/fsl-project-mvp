"""An attack has to be able to come from somewhere other than one city.

A map with one pin is a proof that geolocation works, not a range. And window
correlation matches alerts by source address, so a range with one fixed source
address has never actually tested it.

The whole chain end to end: a network declares where it pretends to be, the
attacker leaves by it, Suricata sees that address at a choke point it is
actually watching, the ingest pipeline resolves it, and the map draws it in a
different place. Every link is silent when it breaks - a missing subnet in
HOME_NET or an unwatched interface produces no alert at all, which reads as a
defence that missed rather than a range that was not listening.
"""

import ipaddress

import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

CASE = "sqli-login-bypass"


@pytest.fixture(scope="module")
def origins(stack_is_up):
    listed = requests.get(f"{PLATFORM_URL}/api/origins/", timeout=120)
    assert listed.status_code == 200, listed.text
    return listed.json()["origins"]


@pytest.fixture(scope="module")
def elsewhere(origins):
    """An origin that is not the one everything has always come from."""
    other = [o for o in origins if not o["default"]]
    assert other, "the stack declares only one place to attack from"
    return other[0]


def test_the_stack_offers_more_than_one_place_to_attack_from(origins):
    assert len(origins) >= 2, f"only {[o['id'] for o in origins]}"


def test_each_origin_is_a_different_subnet(origins):
    # The bridge driver refuses more than one subnet on a network, which is
    # why each of these is a network of its own. Two sharing a subnet would
    # geolocate to the same pin and rotation would be decoration.
    subnets = [o["subnet"] for o in origins]

    assert len(set(subnets)) == len(subnets), subnets


def test_an_origin_s_address_is_actually_on_its_subnet(origins):
    # Read off Docker, not assembled: an address outside its own subnet would
    # mean the attacker is not attached where the label says it is.
    for origin in origins:
        assert ipaddress.ip_address(origin["source_ip"]) in ipaddress.ip_network(
            origin["subnet"]
        ), f"{origin['id']}: {origin['source_ip']} is not in {origin['subnet']}"


def test_exactly_one_origin_is_the_front_door(origins):
    assert [o["id"] for o in origins if o["default"]].__len__() == 1


@pytest.fixture(scope="module")
def two_places(elsewhere, stack_is_up):
    """The same attack sent twice, from two different countries."""
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]

    for origin in ("", elsewhere["id"]):
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": CASE, "origin": origin}, timeout=300,
        )
        assert sent.status_code == 201, sent.text
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    def both_detected(totals):
        return sum(
            1 for c in totals["per_case"] if c["name"] == CASE and c["detected"]
        ) >= 2

    score_when_ready(session_id, until=both_detected)
    return {
        "session_id": session_id,
        "detections": requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
        ).json(),
        "map": requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
        ).json(),
    }


def test_an_attack_sent_from_elsewhere_arrives_from_elsewhere(two_places, elsewhere):
    subnet = ipaddress.ip_network(elsewhere["subnet"])
    sources = {d["src_ip"] for d in two_places["detections"] if d["src_ip"]}
    from_there = {ip for ip in sources if ipaddress.ip_address(ip) in subnet}

    assert from_there, (
        f"nothing arrived from {elsewhere['label']} ({subnet}); the alerts came "
        f"from {sorted(sources)}. Either the attack never left by that segment "
        f"or Suricata is not watching the interface it arrived on."
    )


def test_the_two_attacks_did_not_come_from_the_same_address(two_places):
    sources = {d["src_ip"] for d in two_places["detections"] if d["src_ip"]}

    assert len(sources) >= 2, f"every alert came from {sources}"


def test_the_map_draws_more_than_one_place(two_places):
    countries = {p["country"] for p in two_places["map"]["points"]}

    assert len(countries) >= 2, (
        f"the map has one pin - {sorted(countries)} - so either the second "
        f"origin never reached the target or its range geolocates to nothing"
    )


def test_rotation_does_not_stay_in_one_place(stack_is_up, origins):
    # Nothing is asserted about the order: what matters is that consecutive
    # attacks stop coming from one address, which is what window correlation
    # has never had to cope with.
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
