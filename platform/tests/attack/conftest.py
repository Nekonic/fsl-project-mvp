from dataclasses import replace

import pytest

from attack import service
from cr import config
from tests import rounds
from testing.fakerange import AttackRange

HP = {"budget": 100, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2}


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    reached = AttackRange()
    built = config.build()
    chosen = replace(built, box=replace(built.box, default_origin="ru", target_url="http://board.com"),
                     jump=replace(built.jump, directory=str(tmp_path / "jump"), host="jump.range.test", port=2222))
    monkeypatch.setattr(service, "configured", lambda: chosen)
    monkeypatch.setattr(service, "range_of", lambda found: reached)
    return reached


@pytest.fixture
def make_round(db, cloud):
    def made(*, hp=None, phase="running", objectives=(), fill=True):
        found = rounds.opened(rounds.problem(objectives=objectives), phase=phase)
        if hp is not None:
            found.snapshot["round"]["hp"] = {**HP, **hp}
            found.save(update_fields=["snapshot"])
        if fill and phase == "running":
            service.fill_pool(found)
        return found

    return made


@pytest.fixture
def attack_round(make_round):
    return make_round()


@pytest.fixture
def attacker(attack_round, learner):
    return rounds.seated(attack_round, "attack", learner)


@pytest.fixture
def as_attacker(browser, attacker):
    browser.force_authenticate(attacker.user)
    return browser


def url(found, rest: str) -> str:
    return f"/api/rounds/{found.pk}/attack/{rest}"


def codes(answer) -> list[str]:
    return [error["code"] for error in answer.json()["errors"]]
