import ipaddress

import pytest
import requests

from conftest import PLATFORM_URL
from shared_sessions import shared_session

@pytest.fixture(scope="module")
def drawn(full_run):
    return full_run["topology"]

def test_every_address_on_the_picture_is_on_its_own_subnet(drawn):
    for segment in drawn["segments"]:
        network = ipaddress.ip_network(segment["subnet"])
        for box in segment["nodes"]:
            assert ipaddress.ip_address(box["address"]) in network, (
                f"{box['name']} drawn on {segment['id']} at {box['address']}"
            )

def test_the_running_range_matches_what_was_declared(full_run):
    import pathlib

    import yaml

    declared = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1]
         / "platform/range/declaration.yaml").read_text()
    )
    fixed = {s["id"] for s in declared["segments"] if not s.get("origins")}
    origins = {o["id"] for s in declared["segments"] for o in s.get("origins") or []}

    shape = full_run["topology"]
    standing = {s["id"] for s in shape["segments"]}

    assert fixed <= standing and standing - fixed <= origins, (
        f"the range standing up is not the one that was declared. "
        f"Only running: {sorted(standing - fixed - origins)}. "
        f"Declared and missing: {sorted(fixed - standing)}"
    )
    assert declared["default_origin"] in standing, (
        f"no origin network carries the default origin "
        f"{declared['default_origin']!r}; standing: {sorted(standing)}"
    )


@pytest.fixture(scope="module")
def live_map(stack_is_up):
    with shared_session() as session_id:
        return requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=120).json()["map"]


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
