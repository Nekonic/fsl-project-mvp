from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from cr import config
from testing.fakerange import RU, AttackRange
from tests import rounds
from training.attack import actions as service
from training.attack import origins


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    reached = AttackRange()
    built = config.build()
    chosen = replace(built, box=replace(built.box, default_origin="ru", target_url="http://board.com"),
                     jump=replace(built.jump, directory=str(tmp_path / "jump"), host="jump.range.test", port=2222))
    for module in (service, origins):
        monkeypatch.setattr(module, "configured", lambda: chosen)
        monkeypatch.setattr(module, "range_of", lambda found: reached)
    return reached


@pytest.fixture
def make_round(db, cloud):
    def made(*, phase="running", objectives=(), fill=True, floor=None):
        found = rounds.opened(rounds.problem(objectives=objectives), phase=phase)
        if floor is not None:
            found.snapshot["round"]["limit_floor_rpm"] = floor
            found.save(update_fields=["snapshot"])
        if fill and phase == "running":
            origins.fill_pool(found)
        return found

    return made


@pytest.fixture
def attack_round(make_round):
    return make_round()


@pytest.fixture
def attacker(attack_round, learner):
    return rounds.playing(attack_round, "attack", learner)


@pytest.fixture
def as_attacker(browser, attacker):
    browser.force_authenticate(attacker.user)
    return browser


def url(found, rest: str) -> str:
    return f"/api/rounds/{found.pk}/attack/{rest}"


def codes(answer) -> list[str]:
    return [error["code"] for error in answer.json()["errors"]]


def denied_line(ip=RU) -> str:
    return (f"2026/11/21 10:00:00 [error] 812#812: *41 access forbidden by rule, client: {ip}, server: board.com, "
            'request: "GET /admin/ HTTP/1.1", host: "board.com"')


def limited_line(ip=RU, zone="perip") -> str:
    return (f'2026/11/21 10:00:00 [error] 812#812: *42 limiting requests, excess: 5.120 by zone "{zone}", '
            f'client: {ip}, server: board.com, request: "GET / HTTP/1.1", host: "board.com"')


def error_document(at, line: str) -> dict:
    stamp = at.isoformat().replace("+00:00", "Z")
    return {"@timestamp": stamp, "event": {"module": "nginx_error"}, "error": {"message": line}}


def after_start(found, seconds: float = 1.0):
    return found.started + timedelta(seconds=seconds)


def spent_from_log(es, found) -> int:
    with patch("telemetry.elastic.requests.post", es.post):
        return service.spend_from_log(found)
