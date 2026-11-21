import re
from pathlib import Path

from cr.config import EdgeConfig
from sandbox import edge
from testing.fakes import FakeRunner

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "deploy/roles/infra/edge.nft"
INFRA = ROOT / "deploy/roles/infra"


def ruleset() -> str:
    return EDGE.read_text()


def declared_sets() -> dict[str, str]:
    return dict(re.findall(r"set (\w+) \{\s*type (\w+)\s*\}", ruleset()))


def chain(name: str) -> list[str]:
    body = ruleset().split(f"chain {name} {{", 1)[1].split("}", 1)[0]
    return [line.strip() for line in body.splitlines() if line.strip()]


def test_the_table_and_its_two_sets_are_the_ones_the_edge_seam_fills():
    config = EdgeConfig()
    router = FakeRunner()

    edge.refill(router, ["5.188.10.10"], ["103.152.220.12"], config)

    assert f"table {config.family} {config.table} {{" in ruleset()
    assert declared_sets() == {config.pool: "ipv4_addr", config.spent: "ipv4_addr"}
    for written in router.sent[0].stdin.splitlines():
        family, table, name = written.split()[2:5]
        assert (family, table) == (config.family, config.table) and name in declared_sets()


def test_a_spent_origin_is_dropped_before_its_open_connections_are_let_through():
    forward = chain("forward")
    spent = forward.index('iifname "@wan@" ip saddr @spent drop')

    assert spent < forward.index('iifname "@wan@" ct state established,related accept'), (
        "an open keep-alive or sqlmap connection of a spent origin has to stop too")
    assert spent < forward.index('iifname "@wan@" ct status dnat accept')


def test_an_address_outside_the_pool_is_dropped_before_its_open_connections_are_let_through():
    forward = chain("forward")
    outside = forward.index('iifname "@wan@" ip saddr != @pool drop')

    assert outside < forward.index('iifname "@wan@" ct state established,related accept'), (
        "an unused origin-subnet address that HP never charges must not reach the target")
    assert outside < forward.index('iifname "@wan@" ct status dnat accept')


def test_slot_boot_stays_the_only_loader_and_a_reload_starts_with_empty_sets_the_round_start_fills():
    text = ruleset()
    boot = (INFRA / "slot-boot").read_text()

    assert text.startswith("table ip edge\ndelete table ip edge\n")
    assert "elements" not in text, "the sets carry no addresses of their own; sandbox/edge.py adds them"
    assert '"$SHARE/edge.nft" | nft -f -' in boot


def test_the_infra_carries_the_tools_the_edge_seam_runs():
    installed = re.search(r"^installed (.+)$", (INFRA / "install.sh").read_text(), re.M)[1].split()

    assert {"nftables", "conntrack"} <= set(installed), "edge.spend flushes the origin's conntrack entries"
