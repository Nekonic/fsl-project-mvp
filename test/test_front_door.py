import ipaddress

import pytest
import yaml

from range import DECLARATION


def declared_origins() -> list[ipaddress.IPv4Network]:
    document = yaml.safe_load(DECLARATION.read_text())
    return [ipaddress.ip_network(origin["subnet"]) for segment in document["segments"]
            for origin in segment.get("origins") or []]


@pytest.fixture
def probe(terminal_session):
    token, alerts = terminal_session["front"]
    assert alerts, f"the probe {token} raised no alert at all, so nothing can be said about it"
    return terminal_session["origin"], alerts


def test_the_front_door_is_on_the_outside(probe):
    origin, alerts = probe
    sources = {alert["src_ip"] for alert in alerts}
    outside = declared_origins()

    assert {ip for ip in sources if any(ipaddress.ip_address(ip) in network for network in outside)}, (
        f"an attack through the published port arrived from {sorted(sources)}, none of it from a declared "
        f"origin - the way in is on the inside of the estate"
    )
    assert origin["ip"] in sources, f"the box wore {origin} and its probe arrived from {sorted(sources)}"
