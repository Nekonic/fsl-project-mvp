import json

import pytest

from scoring import baseline as referee
from tests import rounds
from tests.scoring.targets import TRUTH, board_target
from tests.training.attack.conftest import url
from training.attack import actions

pytestmark = pytest.mark.django_db


@pytest.fixture
def looted_round(attacker):
    referee.take_baseline(attacker.round, board_target())
    return attacker.round


def test_loot_is_judged_by_the_referee_and_never_echoes_the_secret(as_attacker, looted_round):
    answer = as_attacker.post(url(looted_round, "loot/"), {"value": [{"username": "admin", "hash": TRUTH["admin"]}]},
                              format="json")

    body = answer.json()
    assert answer.status_code == 200
    assert body["lost"] is True and body["objective"]["key"] == "board-auth-user-admin"
    assert TRUTH["admin"] not in json.dumps(body)


def test_loot_that_takes_several_tiers_names_every_objective_that_fell(as_attacker, looted_round):
    answer = as_attacker.post(url(looted_round, "loot/"), {"value": [{"username": "admin", "hash": TRUTH["admin"]}]},
                              format="json")

    assert [one["key"] for one in answer.json()["objectives"]] == ["board-auth-user-admin", "board-auth-user-partial"]


def test_wrong_loot_loses_nothing(as_attacker, looted_round):
    answer = as_attacker.post(url(looted_round, "loot/"), {"value": [{"username": "admin", "hash": "nope"}]},
                              format="json")

    assert answer.json()["lost"] is False and answer.json()["objective"] is None


def test_the_state_says_whether_the_wargame_takes_loot(as_attacker, looted_round):
    assert as_attacker.get(url(looted_round, "state/")).json()["takes_loot"] is True
    assert actions.state(rounds.opened(rounds.problem("corp"))).takes_loot is False


def test_the_state_names_the_brief_the_target_the_objectives_and_every_origin(as_attacker, looted_round):
    as_attacker.post(url(looted_round, "loot/"), {"value": [{"username": "admin", "hash": TRUTH["admin"]}]},
                     format="json")

    state = as_attacker.get(url(looted_round, "state/")).json()

    assert (state["round"], state["phase"], state["matchup"]) == (looted_round.pk, "running", "def_vs_bot")
    assert state["brief"]["title"] == "Placeholder round"
    assert state["target"] == {"public_url": "http://board.com", "hosts": ["board.com"]}
    shown = {objective["key"]: objective["state"] for objective in state["objectives"]}
    assert (shown["board-auth-user-admin"], shown["board-auth-user-full"]) == ("lost", "kept")
    assert all(set(objective) == {"key", "name", "state"} for objective in state["objectives"])
    assert [origin["id"] for origin in state["origins"]] == ["ru", "br", "us"]
    assert all(origin["spent_at"] is None and origin["spent_by"] == "" for origin in state["origins"])
