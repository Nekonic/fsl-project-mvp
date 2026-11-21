import json

import pytest

from cr import errors
from scoring import baseline as service
from testing.fakes import FakeRunner, FakeTarget
from tests import rounds
from tests.scoring.targets import TRUTH

pytestmark = pytest.mark.django_db


def test_the_board_baseline_sets_fresh_passwords_then_reads_inside_the_board_through_its_read_path(board_target):
    found = rounds.opened(rounds.problem())

    taken = service.take_baseline(found, board_target, {"jiwoo": "fresh-one"})

    found.refresh_from_db()
    assert taken == TRUTH and found.baseline == TRUTH
    assert board_target.reached == ["board"]
    rotated, read = board_target.runners["board"].sent
    assert rotated.argv == ["python", "manage.py", "set_passwords"]
    assert json.loads(rotated.stdin) == {"jiwoo": "fresh-one"}
    assert "http://127.0.0.1:8000/internal/auth-users" in read.text


def test_a_board_whose_passwords_cannot_be_set_refuses_the_baseline_and_keeps_none():
    found = rounds.opened(rounds.problem())
    broken = FakeTarget({"board": FakeRunner().answer("set_passwords", "Traceback", exit_code=1)})

    with pytest.raises(errors.Unavailable) as refused:
        service.take_baseline(found, broken)

    found.refresh_from_db()
    assert refused.value.code == "ground_truth_unavailable"
    assert found.baseline is None
    assert not broken.runners["board"].matching("/internal/auth-users")


def test_the_board_passwords_are_never_set_without_a_way_into_the_board():
    with pytest.raises(errors.Unavailable) as refused:
        service.take_baseline(rounds.opened(rounds.problem()))

    assert refused.value.code == "ground_truth_unavailable"


def test_the_corp_baseline_snapshots_admins_options_and_posts_from_corp_db(corp_target):
    found = rounds.opened(rounds.problem("corp"))

    service.take_baseline(found, corp_target)

    found.refresh_from_db()
    assert found.baseline == {"admins": [1], "options": {"users_can_register": "0", "default_role": "subscriber"},
                              "posts": [1]}
    assert corp_target.reached == ["corp-db"]
    assert not corp_target.runners["corp-db"].matching("set_passwords")


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


def test_a_probe_allocation_reads_the_truth_to_redact_from_the_wargame_alone(board_target):
    wargame = rounds.opened(rounds.problem()).snapshot["wargame"]

    truth = service.ground_truth(wargame, board_target)

    assert truth == TRUTH
    assert not board_target.runners["board"].matching("set_passwords")
    assert TRUTH["admin"] not in service.redact(f"hash={TRUTH['admin']}", truth)


def test_the_corp_truth_is_its_snapshot_and_has_no_secret_to_redact(corp_target):
    wargame = rounds.opened(rounds.problem("corp")).snapshot["wargame"]

    truth = service.ground_truth(wargame, corp_target)

    assert truth["admins"] == [1]
    assert service.redact("[1] subscriber", truth) == "[1] subscriber"
