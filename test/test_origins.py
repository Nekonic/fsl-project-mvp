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
