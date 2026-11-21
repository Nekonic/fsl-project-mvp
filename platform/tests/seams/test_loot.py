from unittest.mock import patch

import pytest

from cr.config import GroundTruthConfig
from scoring import loot

BOARD = GroundTruthConfig(board_url="http://board:8000")
READ = "/internal/auth-users"

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}

SPEC = {
    "secret": {"read_path": "/internal/auth-users"},
    "tiers": [
        {"key": "board-auth-user-partial", "name": "partial", "difficulty": 2,
         "min_matched": 1},
        {"key": "board-auth-user-admin", "name": "admin", "difficulty": 4,
         "account": "admin"},
        {"key": "board-auth-user-full", "name": "full", "difficulty": 5,
         "coverage": 1.0},
    ],
}


def test_canonicalize_accepts_dicts_pairs_and_mappings():
    pairs = loot.canonicalize([{"username": "admin", "hash": "h1"},
                               {"username": "jiwoo", "password": "h2"},
                               ["minseo", "h3"]])
    assert pairs == {("admin", "h1"), ("jiwoo", "h2"), ("minseo", "h3")}
    assert loot.canonicalize({"admin": "h1"}) == {("admin", "h1")}
    assert loot.canonicalize("garbage") == set()
    assert loot.canonicalize([{"username": "admin"}, 7, None]) == set()


def test_matched_requires_the_exact_stored_hash():
    submitted = [{"username": "admin", "hash": TRUTH["admin"]},
                 {"username": "jiwoo", "hash": "pbkdf2_sha256$600000$bbb$WRONG="},
                 {"username": "minseo", "password": "minseo1234"}]
    assert loot.matched(submitted, TRUTH) == {"admin"}


@pytest.mark.parametrize("taken, keys, share", [
    ({"jiwoo"}, ["board-auth-user-partial"], 1 / 3),
    ({"admin"}, ["board-auth-user-partial", "board-auth-user-admin"], 1 / 3),
    (set(TRUTH), ["board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"], 1.0),
])
def test_the_tiers_fired_follow_what_was_taken(taken, keys, share):
    fired, coverage = loot.tiers_fired(SPEC, taken, TRUTH)
    assert [t["key"] for t in fired] == keys
    assert coverage == pytest.approx(share)


def test_ground_truth_reads_the_declared_read_path():
    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"admin": "h1"}'

    with patch("scoring.loot.urllib.request.urlopen", return_value=Fake()) as opened:
        assert loot.ground_truth(READ, BOARD) == {"admin": "h1"}
    assert opened.call_args.args[0].endswith("/internal/auth-users")


def test_ground_truth_rejects_a_body_that_is_not_a_username_map():
    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'[{"username": "admin"}]'

    with patch("scoring.loot.urllib.request.urlopen", return_value=Fake()):
        with pytest.raises(loot.GroundTruthUnavailable):
            loot.ground_truth(READ, BOARD)


def test_on_the_range_host_the_ground_truth_is_read_inside_the_board_s_own_container():
    from sandbox.runner import Ran

    seen = []

    def inside(argv, stdin=None, timeout=60.0):
        seen.append(argv)
        return Ran(0, '{"admin": "h1"}')

    assert loot.ground_truth(READ, BOARD, inside=inside) == {"admin": "h1"}
    assert seen[0][:2] == ["python", "-c"] and seen[0][3] == "http://127.0.0.1:8000/internal/auth-users", (
        "the board's network is internal to its slot, so the platform reads it through docker exec")


def test_a_board_that_cannot_be_reached_from_inside_is_unavailable_ground_truth():
    from sandbox.runner import RangeUnavailable

    def inside(argv, stdin=None, timeout=60.0):
        raise RangeUnavailable("ssh: connect timed out")

    with pytest.raises(loot.GroundTruthUnavailable) as refused:
        loot.ground_truth(READ, BOARD, inside=inside)
    assert refused.value.code == "ground_truth_unavailable"
