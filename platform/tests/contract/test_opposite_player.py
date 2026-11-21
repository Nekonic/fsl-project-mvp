from pathlib import Path

import pytest
import yaml

from tests.shape import refused
from tests.training.round.conftest import cloud, allocation, other, problem, pvp
from training.round import lifecycle as service

SCHEMA = Path(__file__).resolve().parents[3] / "openapi" / "schema.yaml"
ROUND = "/api/rounds/{round_id}/"
SIDES = ("attack", "defence")
SHARED = {
    ROUND: "round",
    f"{ROUND}events/": "events",
    f"{ROUND}score/": "score",
    f"{ROUND}topology/": "topology",
    f"{ROUND}site/requests/": "site_requests",
    f"{ROUND}terminal-auth/attack/": "terminal_attack",
    f"{ROUND}terminal-auth/defence/": "terminal_defence",
}
FILLED = {"run_id": "1", "test_id": "1", "sid": "9000001"}

__all__ = ["cloud", "allocation", "other", "problem"]


def round_gets() -> list[str]:
    paths = yaml.safe_load(SCHEMA.read_text())["paths"]
    return sorted(path for path, item in paths.items() if path.startswith(ROUND) and "get" in item)


def side_of(path: str) -> str | None:
    rest = path.removeprefix(ROUND)
    return next((side for side in SIDES if rest.startswith(f"{side}/")), None)


def other_side(side: str) -> str:
    return SIDES[1 - SIDES.index(side)]


def filled(path: str, round_id: int) -> str:
    return path.format(round_id=round_id, **FILLED)


@pytest.fixture
def defender(make_user):
    return make_user("defender")


@pytest.fixture
def running(allocation, problem, other, defender):
    return service.start_round(pvp(allocation, problem, other, defender))


@pytest.fixture
def players(running, other, defender):
    return {"attack": other, "defence": defender}


def test_every_round_scoped_read_is_walked_by_this_test():
    unwalked = [path for path in round_gets() if side_of(path) is None and path not in SHARED]

    assert unwalked == [], "add the new round read to SHARED with what the other player may see"


@pytest.mark.parametrize("path", [path for path in round_gets() if side_of(path)])
def test_a_side_s_reads_refuse_the_player_across_the_table(browser, running, players, path):
    browser.force_authenticate(players[other_side(side_of(path))])

    refused(browser.get(filled(path, running.pk)), 403, "not_a_player")


def test_a_player_reads_neither_the_other_player_s_site_requests_nor_its_round_secret(browser, running, players):
    browser.force_authenticate(players["attack"])
    browser.get(f"/site-proxy/{running.pk}/board.com/posts/1/")
    browser.force_authenticate(players["defence"])

    assert browser.get(f"/api/rounds/{running.pk}/site/requests/").json() == []
    shown = browser.get(f"/api/rounds/{running.pk}/").json()
    assert not {"snapshot", "baseline", "read_of"} & set(shown)
