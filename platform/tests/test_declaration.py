import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARATION = ROOT / "platform" / "range" / "declaration.yaml"


def test_the_default_origin_has_to_be_somewhere_an_attack_can_start():
    from range.declared import Declaration, Segment

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

    nets = [ipaddress.ip_network(o["subnet"]) for o in origins()]
    inside = [ipaddress.ip_network(n) for n in ("172.30.0.0/24", "172.31.0.0/24", "10.20.0.0/24")]

    assert all(net.prefixlen == 24 for net in nets)
    assert not [
        (str(a), str(b)) for i, a in enumerate(nets) for b in nets[i + 1:] + inside if a.overlaps(b)
    ]
