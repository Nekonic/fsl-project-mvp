from pathlib import Path

import pytest
import yaml

from telemetry import events as log
from tests.shape import refused
from tests.training.round.conftest import cloud, allocation, other, problem, pvp
from training.round import lifecycle as service

SCHEMA = Path(__file__).resolve().parents[3] / "openapi" / "schema.yaml"
ROUND = "/api/rounds/{round_id}/"
SIDES = ("attack", "defence")
SHARED = {
    ROUND: {"allocation", "end_reason", "ended", "ends_at", "kind", "matchup", "phase", "players", "problem", "round",
            "started", "wargame"},
    f"{ROUND}events/": {"events", "next"},
    f"{ROUND}score/": {"errors"},
    f"{ROUND}debrief/": {"errors"},
    f"{ROUND}topology/": {"edges", "nodes", "zones"},
    f"{ROUND}site/requests/": set(),
    f"{ROUND}terminal-auth/attack/": {"errors"},
    f"{ROUND}terminal-auth/defence/": {"errors"},
    f"{ROUND}terminal-auth/ids/": {"errors"},
}
HELD_BACK = ("snapshot", "baseline", "read_of", "attributed_marker")
FILLED = {"run_id": "1", "test_id": "1", "sid": "9000001", "version": "1"}

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
    return service.start_round(pvp(allocation, other, defender))


@pytest.fixture
def players(running, other, defender):
    return {"attack": other, "defence": defender}


def side_paths() -> list[str]:
    return [path for path in round_gets() if side_of(path)]


def test_every_round_scoped_read_is_walked_by_this_test():
    unwalked = [path for path in round_gets() if side_of(path) is None and path not in SHARED]

    assert unwalked == [], "add the new round read to SHARED with the keys either player may see"
    assert side_paths()


@pytest.mark.parametrize("path", side_paths())
def test_a_side_s_reads_refuse_the_player_across_the_table(browser, running, players, path):
    browser.force_authenticate(players[other_side(side_of(path))])

    refused(browser.get(filled(path, running.pk)), 403, "not_a_player")


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("path", sorted(SHARED))
def test_a_shared_read_shows_either_player_only_its_declared_keys_and_never_the_round_secret(browser, running,
                                                                                             players, path, side):
    log.append(running.pk, "objective.lost", {"key": "board-auth-user-admin", "name": "admin",
                                              "attributed_marker": "act-1"})
    browser.force_authenticate(players[side])

    answer = browser.get(filled(path, running.pk))
    body = answer.json() if answer.content else None

    assert (set(body) if isinstance(body, dict) else set()) <= SHARED[path]
    assert [key for key in HELD_BACK if f'"{key}"' in answer.content.decode()] == []
