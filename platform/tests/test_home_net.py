import ipaddress
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCKER_DEFAULT_POOLS = ("172.17.0.0/16", "172.31.0.0/16", "192.168.0.0/20", "192.168.240.0/20")


def home_net():
    text = (ROOT / "deploy/suricata/suricata.yaml").read_text().split("\n", 2)[2]
    listed = yaml.safe_load(text)["vars"]["address-groups"]["HOME_NET"]
    return [ipaddress.ip_network(entry) for entry in listed.strip("[]").split(",")]


def origins():
    declared = yaml.safe_load((ROOT / "platform/range/declaration.yaml").read_text())
    return [
        ipaddress.ip_network(origin["subnet"])
        for segment in declared["segments"] for origin in segment.get("origins") or []
    ]


def edges():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    return [
        ipaddress.ip_network(entry["ipam"]["config"][0]["subnet"])
        for entry in compose["networks"].values()
        if entry.get("labels", {}).get("fsl.origin")
    ]


def test_a_session_estate_from_any_default_pool_is_home():
    outside = [
        pool for pool in DOCKER_DEFAULT_POOLS
        if not any(ipaddress.ip_network(pool).subnet_of(net) for net in home_net())
    ]

    assert not outside, (
        f"a session's estate floats in Docker's default pools, and {outside} is "
        f"not in HOME_NET, so the inside-leg rules never match it"
    )


def test_home_holds_no_origin_except_the_waf_s_own_edges():
    private = [net for net in home_net() if net.is_private]
    inside = [str(o) for o in origins() if any(o.overlaps(net) for net in private)]

    assert not inside, f"origins {inside} fall in HOME_NET's private ranges"
    assert {net for net in home_net() if not net.is_private} == set(edges()), (
        "HOME_NET lists outside subnets that are not the WAF's edges"
    )
