from pathlib import Path

import yaml

from cr.config import VpnConfig
from sandbox import vpn

ROOT = Path(__file__).resolve().parents[2]


def test_the_profile_text_names_the_accounts_port_address_and_every_wargames_target_address():
    config = VpnConfig(first_port=51820, last_port=51829, network="10.99.0.0/16")
    pc, server = vpn.key_pair(), vpn.key_pair()

    text = vpn.profile_text(vpn.profile_for(pc.private, 51823, server.public, "192.0.2.10", ROOT, config))

    assert f"PrivateKey = {pc.private}\n" in text and f"PublicKey = {server.public}\n" in text
    assert "Address = 10.99.0.5/32\n" in text and "Endpoint = 192.0.2.10:51823\n" in text
    assert "AllowedIPs = 121.134.88.42/32, 10.99.0.1/32\n" in text
    for topology in ROOT.glob("wargames/*/topology.yaml"):
        wan = [port["address"] for node in yaml.safe_load(topology.read_text())["nodes"].values()
               for port in node["ports"] if port["lan"] == "internet" and port.get("address")]
        assert wan and all(f"{address}/32" in text for address in wan), topology


def test_the_relay_keeps_answering_the_learners_pc_while_it_is_heard_from_and_moves_only_once_it_falls_silent():
    relay = vpn.Relay(VpnConfig(first_port=51820, last_port=51829, network="10.99.0.0/16"))
    learner, stranger = ("198.51.100.7", 40000), ("203.0.113.9", 40001)

    relay.heard_from(51820, learner, 100.0)
    relay.heard_from(51820, stranger, 101.0)
    relay.heard_from(51820, learner, 120.0)
    relay.heard_from(51820, stranger, 120.0 + vpn.CLIENT_IDLE_SECONDS - 1)
    assert relay.clients[51820] == learner

    relay.heard_from(51820, stranger, 120.0 + vpn.CLIENT_IDLE_SECONDS + 1)
    assert relay.clients[51820] == stranger
