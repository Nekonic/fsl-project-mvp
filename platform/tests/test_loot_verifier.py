from unittest.mock import patch

import pytest

from api import loot

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
                 {"username": "jiwoo", "hash": "pbkdf2_sha256$600000$bbb$WRONG="}]
    assert loot.matched(submitted, TRUTH) == {"admin"}


def test_a_plaintext_guess_never_matches_a_salted_hash():
    assert loot.matched([{"username": "admin", "password": "admin1234"}], TRUTH) == set()


def test_a_single_non_admin_row_fires_only_partial():
    fired, coverage = loot.tiers_fired(SPEC, {"jiwoo"}, TRUTH)
    assert [t["key"] for t in fired] == ["board-auth-user-partial"]
    assert coverage == pytest.approx(1 / 3)


def test_a_single_admin_row_fires_partial_and_admin():
    fired, _ = loot.tiers_fired(SPEC, {"admin"}, TRUTH)
    assert [t["key"] for t in fired] == ["board-auth-user-partial", "board-auth-user-admin"]


def test_a_whole_table_fires_all_three_tiers():
    fired, coverage = loot.tiers_fired(SPEC, set(TRUTH), TRUTH)
    assert [t["key"] for t in fired] == [
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    ]
    assert coverage == 1.0


def test_ground_truth_reads_the_declared_read_path():
    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"admin": "h1"}'

    with patch("api.loot.wargames.objectives", return_value=SPEC), patch(
        "api.loot.urllib.request.urlopen", return_value=Fake()
    ) as opened:
        assert loot.ground_truth("board") == {"admin": "h1"}
    assert opened.call_args.args[0].endswith("/internal/auth-users")


def test_ground_truth_raises_when_the_channel_is_unreadable():
    import urllib.error

    with patch("api.loot.wargames.objectives", return_value=SPEC), patch(
        "api.loot.urllib.request.urlopen",
        side_effect=urllib.error.URLError("refused"),
    ):
        with pytest.raises(loot.GroundTruthUnavailable):
            loot.ground_truth("board")
