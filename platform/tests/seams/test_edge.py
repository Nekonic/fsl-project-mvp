import json

import pytest

from cr.config import EdgeConfig
from sandbox import edge
from sandbox.runner import RangeUnavailable
from testing.fakes import FakeRunner


def test_spending_an_origin_adds_it_to_the_spent_set_and_drops_its_open_connections():
    router = FakeRunner()

    edge.spend(router, "5.188.10.10")

    assert router.sent[0].argv == ["nft", "add element ip edge spent { 5.188.10.10 }"]
    assert router.sent[1].argv == ["conntrack", "-D", "-s", "5.188.10.10"]


def test_an_origin_with_no_open_connection_is_still_spent():
    router = FakeRunner().answer("conntrack", "0 flow entries have been deleted", 1)

    edge.spend(router, "5.188.10.10")

    assert router.sent[0].argv == ["nft", "add element ip edge spent { 5.188.10.10 }"]
    assert router.sent[1].argv == ["conntrack", "-D", "-s", "5.188.10.10"]


def test_a_conntrack_that_fails_otherwise_is_reported():
    with pytest.raises(RangeUnavailable):
        edge.spend(FakeRunner().answer("conntrack", "conntrack: command not found", 127), "5.188.10.10")


def test_refilling_adds_the_pool_and_the_spent_addresses_in_one_load():
    router = FakeRunner()

    edge.refill(router, ["5.188.10.10", "103.152.220.11", "5.188.10.10"], ["103.152.220.12"])

    [load] = router.sent
    assert load.argv == ["nft", "-f", "-"]
    assert load.stdin == ("add element ip edge pool { 5.188.10.10, 103.152.220.11 }\n"
                          "add element ip edge spent { 103.152.220.12 }\n")


def test_restarting_empties_both_sets_and_adds_the_new_addresses_in_one_load():
    router = FakeRunner()

    edge.restart(router, ["5.188.10.10"], [])

    [load] = router.sent
    assert load.argv == ["nft", "-f", "-"]
    assert load.stdin == ("flush set ip edge pool\n"
                          "flush set ip edge spent\n"
                          "add element ip edge pool { 5.188.10.10 }\n")


def test_nothing_to_add_sends_nothing():
    router = FakeRunner()

    edge.refill(router, [], [])
    edge.admit(router, [])

    assert router.sent == []


@pytest.mark.parametrize("address", ["5.188.10.10 }; flush ruleset; {", "5.188.10.0/24", "::1", ""])
def test_only_single_ipv4_addresses_reach_the_router(address):
    with pytest.raises(ValueError):
        edge.spend(FakeRunner(), address)


def test_the_set_names_come_from_config():
    router = FakeRunner()

    edge.admit(router, ["5.188.10.10"], EdgeConfig(family="inet", table="range", pool="allowed"))

    assert router.sent[0].stdin == "add element inet range allowed { 5.188.10.10 }\n"


def test_a_set_is_listed_from_nft_s_json():
    listing = {"nftables": [{"metainfo": {}}, {"set": {"name": "spent", "elem": ["5.188.10.10", "1.128.0.10"]}}]}

    assert edge.listed(FakeRunner().answer("list set", json.dumps(listing)), "spent") == {"5.188.10.10", "1.128.0.10"}


def test_a_router_that_refuses_is_range_unavailable():
    with pytest.raises(RangeUnavailable):
        edge.spend(FakeRunner().answer("add element", "Error: No such file or directory; set spent", 1), "5.188.10.10")

