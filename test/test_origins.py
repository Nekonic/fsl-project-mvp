import pytest

import plays


@pytest.fixture(scope="module")
def elsewhere(origins_session):
    other = origins_session["elsewhere"]
    assert other, "the round offers only one place to attack from"
    return other


def test_the_round_s_origins_are_the_ones_the_attack_state_lists(origins_session):
    listed = {origin["ip"] for origin in origins_session["origins"]}

    assert origins_session["first"]["ip"] in listed and len(listed) > 1, origins_session["origins"]


def test_an_attack_sent_from_elsewhere_arrives_from_elsewhere(origins_session, elsewhere):
    sources = {alert["src_ip"] for alert in plays.marked(origins_session["alerts"], origins_session["moved"])}

    assert elsewhere["ip"] in sources, (
        f"nothing arrived from {elsewhere['label']} ({elsewhere['ip']}); the alerts came "
        f"from {sorted(sources)}. Either the attack never left by that origin "
        f"or Suricata is not watching the interface it arrived on."
    )


def test_the_first_attack_arrived_from_the_first_origin(origins_session):
    sources = {alert["src_ip"] for alert in plays.marked(origins_session["alerts"], origins_session["front"])}

    assert origins_session["first"]["ip"] in sources, sources
