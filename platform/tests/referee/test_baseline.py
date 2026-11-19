import pytest

from cr import errors
from referee import service
from testing.fakes import FakeRunner, FakeTarget
from tests import rounds
from tests.referee.targets import TRUTH

pytestmark = pytest.mark.django_db


def test_the_board_baseline_is_read_inside_the_board_through_its_declared_read_path(board_target):
    found = rounds.opened(rounds.problem())

    taken = service.take_baseline(found, board_target)

    found.refresh_from_db()
    assert taken == TRUTH and found.baseline == TRUTH
    assert board_target.reached == ["board"]
    assert "http://127.0.0.1:8000/internal/auth-users" in board_target.runners["board"].texts()[0]


def test_the_corp_baseline_snapshots_admins_options_and_posts_from_corp_db(corp_target):
    found = rounds.opened(rounds.problem("corp"))

    service.take_baseline(found, corp_target)

    found.refresh_from_db()
    assert found.baseline == {"admins": [1], "options": {"users_can_register": "0", "default_role": "subscriber"},
                              "posts": [1]}
    assert corp_target.reached == ["corp-db"]


def test_a_board_that_cannot_be_read_refuses_the_baseline_and_keeps_none():
    found = rounds.opened(rounds.problem())
    broken = FakeTarget({"board": FakeRunner().answer("/internal/auth-users", "Traceback", exit_code=1)})

    with pytest.raises(errors.Unavailable) as refused:
        service.take_baseline(found, broken)

    found.refresh_from_db()
    assert refused.value.code == "ground_truth_unavailable" and refused.value.status == 503
    assert found.baseline is None


def test_a_corp_baseline_needs_a_way_into_the_target():
    with pytest.raises(errors.Unavailable) as refused:
        service.take_baseline(rounds.opened(rounds.problem("corp")))

    assert refused.value.code == "ground_truth_unavailable"


def test_a_target_role_the_range_cannot_reach_is_a_range_fault():
    with pytest.raises(errors.Unavailable) as refused:
        service.take_baseline(rounds.opened(rounds.problem()), FakeTarget({}))

    assert refused.value.code == "range_unavailable"


def test_a_probe_lease_reads_the_truth_to_redact_from_the_wargame_alone(board_target):
    wargame = rounds.opened(rounds.problem()).snapshot["wargame"]

    truth = service.ground_truth(wargame, board_target)

    assert truth == TRUTH
    assert TRUTH["admin"] not in service.redact(f"hash={TRUTH['admin']}", truth)


def test_the_corp_truth_is_its_snapshot_and_has_no_secret_to_redact(corp_target):
    wargame = rounds.opened(rounds.problem("corp")).snapshot["wargame"]

    truth = service.ground_truth(wargame, corp_target)

    assert truth["admins"] == [1]
    assert service.redact("[1] subscriber", truth) == "[1] subscriber"
