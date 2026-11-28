import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
DECLARATION = ROOT / "platform" / "sandbox" / "declaration.yaml"


def test_the_default_origin_has_to_be_somewhere_an_attack_can_start():
    from sandbox.declaration import Declaration, Segment

    inside_only = Declaration(
        segments=(Segment(id="estate", name="Application estate", origin=""),),
        default_origin="estate",
    )

    with pytest.raises(ValueError, match="estate"):
        inside_only.check()


def origins():
    declaration = yaml.safe_load(DECLARATION.read_text())
    return [o for entry in declaration["segments"] for o in entry.get("origins") or []]

def test_each_origin_is_its_own_slash_24_away_from_every_network_the_platform_needs():
    import ipaddress

    from sandbox import cloud_config

    nets = [ipaddress.ip_network(o["subnet"]) for o in origins()]
    example = cloud_config.read(cloud_config.EXAMPLE)
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    slot_lans = [
        cidr
        for path in sorted((ROOT / "wargames").glob("*/topology.yaml"))
        for cidrs in yaml.safe_load(path.read_text())["lans"].values() for cidr in cidrs
    ]
    inside = [ipaddress.ip_network(n) for n in (
        *slot_lans, example.platform_cidr, example.inside["mgmt"],
        compose["networks"]["mgmt"]["ipam"]["config"][0]["subnet"],
    )]

    assert slot_lans

    assert all(net.prefixlen == 24 for net in nets)
    assert not [
        (str(a), str(b)) for i, a in enumerate(nets) for b in nets[i + 1:] + inside if a.overlaps(b)
    ]


def test_every_origin_names_its_country_in_korean_for_the_console():
    import re

    assert [o["label"] for o in origins() if not re.fullmatch(r"[가-힣]+", o["label"])] == []
