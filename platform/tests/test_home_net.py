import ipaddress
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def home_net():
    text = (ROOT / "deploy/suricata/suricata.yaml").read_text().split("\n", 2)[2]
    listed = yaml.safe_load(text)["vars"]["address-groups"]["HOME_NET"]
    return [ipaddress.ip_network(entry) for entry in listed.strip("[]").split(",")]


def origins():
    declared = yaml.safe_load((ROOT / "platform/sandbox/declaration.yaml").read_text())
    return [
        ipaddress.ip_network(origin["subnet"])
        for segment in declared["segments"] for origin in segment.get("origins") or []
    ]


def lans_by_holding_origins():
    held, estate = [], []
    for path in sorted((ROOT / "wargames").glob("*/topology.yaml")):
        topology = yaml.safe_load(path.read_text())
        origin_lans = {
            port["lan"] for node in topology["nodes"].values()
            for port in node.get("ports") or [] if port.get("origins")
        }
        for lan, cidrs in topology["lans"].items():
            side = held if lan in origin_lans else estate
            side.extend((path.parent.name, lan, ipaddress.ip_network(cidr)) for cidr in cidrs)
    return held, estate


def test_every_slot_lan_without_origins_is_home_and_the_origin_lan_is_not():
    held, estate = lans_by_holding_origins()
    home = home_net()
    outside = [f"{war}:{lan} {net}" for war, lan, net in estate
               if not any(net.subnet_of(h) for h in home)]
    overlapping = [f"{war}:{lan} {net}" for war, lan, net in held
                   if any(net.overlaps(h) for h in home)]

    assert estate and held
    assert not outside, (
        f"{outside} carry the session's estate but are not in HOME_NET, so the "
        f"inside-leg rules never match them"
    )
    assert not overlapping, (
        f"{overlapping} hold the attacker's origins and overlap HOME_NET, so the "
        f"sensor takes the attacker for the inside network"
    )


def test_home_holds_no_origin_at_all():
    inside = [str(o) for o in origins() if any(o.overlaps(net) for net in home_net())]

    assert not inside, (
        f"origins {inside} are in HOME_NET, so the estate sensor takes the attacker "
        f"for the inside network")
