import ipaddress

import pytest

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


def test_the_live_map_draws_each_container_on_the_bridge_it_stands_on_with_an_address_of_that_bridge(drawn):
    live = drawn["map"]
    subnets = {zone["id"]: zone["subnet"] for zone in live["zones"]}
    linked = {(edge["source"], edge["target"].removeprefix("switch:")): edge["address"]
              for edge in live["edges"] if edge["kind"] == "link"}

    assert {("kali", "internet"), ("router", "internet"), ("router", "estate"), ("waf", "estate"),
            ("board.com", "estate"), ("board-db", "board-default")} <= set(linked), linked
    for (host, zone), address in linked.items():
        if subnets[zone]:
            assert ipaddress.ip_address(address) in ipaddress.ip_network(subnets[zone]), (host, zone, address)
