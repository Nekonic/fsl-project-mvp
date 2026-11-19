from pathlib import Path

import pytest
import yaml

from events import kinds, log
from match import service
from tests.match.conftest import cloud, lease, other, problem, pvp
from tests.shape import refused

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

__all__ = ["cloud", "lease", "other", "problem"]


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
def running(lease, problem, other, defender):
    return service.start_round(pvp(lease, problem, other, defender))


@pytest.fixture
def seats(running, other, defender):
    return {"attack": other, "defence": defender}


def test_every_round_scoped_read_is_walked_by_this_test():
    unwalked = [path for path in round_gets() if side_of(path) is None and path not in SHARED]

    assert unwalked == [], "add the new round read to SHARED with what the other seat may see"


@pytest.mark.parametrize("path", [path for path in round_gets() if side_of(path)])
def test_a_side_s_reads_refuse_the_seat_across_the_table(browser, running, seats, path):
    browser.force_authenticate(seats[other_side(side_of(path))])

    refused(browser.get(filled(path, running.pk)), 403, "not_seated")


@pytest.mark.parametrize("side", SIDES)
def test_the_feed_shows_a_seat_no_event_only_the_other_side_sees(browser, running, seats, side):
    log.append(running.pk, "origin.spent", {"ip": "198.51.100.9"}, seat_side="attack")
    log.append(running.pk, "rule.applied", {"engine": "ids", "version": 1}, seat_side="defence")
    browser.force_authenticate(seats[side])

    shown = {event["kind"] for event in browser.get(f"/api/rounds/{running.pk}/events/").json()["events"]}

    assert shown and all(side in kinds.KINDS[kind].visible_to for kind in shown), shown


@pytest.mark.parametrize("side", SIDES)
def test_a_seat_reads_no_score_while_the_round_runs(browser, running, seats, side):
    browser.force_authenticate(seats[side])

    refused(browser.get(f"/api/rounds/{running.pk}/score/"), 409, "round_running")


@pytest.mark.parametrize("side", SIDES)
def test_a_seat_opens_only_its_own_side_s_terminal(browser, running, seats, side):
    browser.force_authenticate(seats[side])

    refused(browser.get(f"/api/rounds/{running.pk}/terminal-auth/{other_side(side)}/"), 403, "not_seated")


def test_the_attack_seat_reads_the_map_without_what_only_the_defence_sees(browser, running, seats, monkeypatch):
    from range import topology

    drawn = {"zones": [], "nodes": [{"id": "ids", "kind": "sensor"}, {"id": "web", "kind": "server"}],
             "edges": [{"id": "e", "source": "web", "target": "ids"}]}
    monkeypatch.setattr(topology, "graph", lambda learner, wiring: drawn)
    browser.force_authenticate(seats["attack"])

    shown = browser.get(f"/api/rounds/{running.pk}/topology/").json()

    assert {node["id"] for node in shown["nodes"]} == {"web"}


def test_a_seat_reads_neither_the_other_seat_s_site_requests_nor_its_round_secret(browser, running, seats):
    browser.force_authenticate(seats["attack"])
    browser.get(f"/site-proxy/{running.pk}/board.com/posts/1/")
    browser.force_authenticate(seats["defence"])

    assert browser.get(f"/api/rounds/{running.pk}/site/requests/").json() == []
    shown = browser.get(f"/api/rounds/{running.pk}/").json()
    assert not {"snapshot", "baseline", "read_of"} & set(shown)
