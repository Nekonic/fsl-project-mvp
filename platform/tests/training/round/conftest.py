import pytest

from testing import factories, fakerange
from testing.fakes import FakeElastic
from training.content import problems as content
from training.round import lease as leases
from training.round import lifecycle as service
from training.round import site


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    made = fakerange.FakeCloud()
    fakerange.HELD["range"] = made
    monkeypatch.setenv("CR_SUBSTRATE", "testing.fakerange.connect")
    monkeypatch.setenv("CR_REFILL_DIR", str(tmp_path / "refill"))
    monkeypatch.setenv("CR_JUMP_DIR", str(tmp_path / "jump"))
    monkeypatch.setattr("sandbox.kibana.session_view_ready", lambda *given, **named: True)
    monkeypatch.setattr("telemetry.elastic.requests.post", FakeElastic().post)
    yield made
    fakerange.HELD.clear()
    site.kept.clear()
    site.jars.clear()


@pytest.fixture
def problem(db):
    return content.save_document(factories.round_problem(objectives=["board-auth-user-admin"]))


@pytest.fixture
def lease(cloud, learner):
    return leases.open_lease(learner, "board")


@pytest.fixture
def as_operator(as_learner):
    return as_learner


@pytest.fixture
def other(make_user):
    return make_user("opponent")


def url(found, rest: str = "") -> str:
    return f"/api/rounds/{found.pk}/{rest}"


def pvp(lease, problem, attacker, defender):
    return service.create_round(lease, problem.pk, "pvp",
                                {"attack": {"username": attacker.username}, "defence": {"username": defender.username}}).round
