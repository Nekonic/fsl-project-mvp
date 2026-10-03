import pytest

import wargames


def test_the_board_declares_a_secret_and_a_read_path():
    spec = wargames.objectives("board")

    assert spec["secret"]["scope"] == "auth_user"
    assert spec["secret"]["read_path"] == "/internal/auth-users"
    assert "username" in spec["secret"]["columns"]
    assert "password" in spec["secret"]["columns"]


def test_the_board_declares_the_partial_admin_and_full_tiers():
    tiers = {t["key"]: t for t in wargames.objectives("board")["tiers"]}

    assert set(tiers) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert tiers["board-auth-user-partial"]["min_matched"] == 1
    assert tiers["board-auth-user-partial"]["difficulty"] == 2
    assert tiers["board-auth-user-admin"]["account"] == "admin"
    assert tiers["board-auth-user-admin"]["difficulty"] == 4
    assert tiers["board-auth-user-full"]["coverage"] == 1.0
    assert tiers["board-auth-user-full"]["difficulty"] == 5


def test_every_tier_carries_an_integer_difficulty_and_a_name():
    for tier in wargames.objectives("board")["tiers"]:
        assert isinstance(tier["difficulty"], int)
        assert isinstance(tier["name"], str) and tier["name"]


def test_an_unknown_wargame_has_no_objective_spec():
    with pytest.raises(wargames.UnknownWargame):
        wargames.objectives("no-such-wargame")
