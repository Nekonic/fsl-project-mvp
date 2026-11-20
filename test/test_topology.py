import ipaddress

import pytest


@pytest.fixture(scope="module")
def live_map(full_run):
    return full_run["topology"]


def test_the_live_map_draws_each_device_on_the_network_it_stands_on_with_an_address_of_that_network(live_map):
    subnets = {zone["id"]: zone["subnet"] for zone in live_map["zones"]}
    links = [edge for edge in live_map["edges"] if edge["kind"] == "link"]
    sensors = {node["id"] for node in live_map["nodes"] if node["kind"] == "sensor"}
    bridged = {}
    for edge in links:
        if edge["source"] in sensors:
            bridged.setdefault(edge["source"], set()).add(edge["target"].removeprefix("switch:"))
    zones_of = {}
    for edge in links:
        if edge["source"] in sensors:
            continue
        zones = bridged.get(edge["target"]) or {edge["target"].removeprefix("switch:")}
        zones_of.setdefault(edge["source"], set()).update(zones)
        held = [subnets[zone] for zone in zones if subnets[zone]]
        if held:
            assert any(ipaddress.ip_address(edge["address"]) in ipaddress.ip_network(subnet) for subnet in held), edge

    assert {"internet"} <= zones_of["kali"] and {"internet"} < zones_of["router"], zones_of
    assert zones_of["waf"] & zones_of["board.com"] and zones_of["board.com"] & zones_of["board-db"], zones_of
    assert {zone["caption"] for zone in live_map["zones"]} >= {"internet", "dmz", "database"}
