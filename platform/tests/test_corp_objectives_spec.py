import wargames


def test_corp_reads_state_from_the_corp_db_container_not_a_wp_endpoint():
    secret = wargames.objectives("corp")["secret"]
    assert secret["role"] == "corp-db"
    assert "corp-db" in secret["read_path"]
    assert "http" not in secret["read_path"]


def test_corp_declares_the_three_graded_objectives():
    tiers = {t["key"]: t for t in wargames.objectives("corp")["tiers"]}
    assert set(tiers) == {"corp-rogue-admin", "corp-self-registration", "corp-content-overwrite"}
    assert tiers["corp-rogue-admin"]["difficulty"] == 5
    assert tiers["corp-rogue-admin"]["effect"] == "rogue_admin"
    assert tiers["corp-self-registration"]["difficulty"] == 4
    assert tiers["corp-self-registration"]["effect"] == "option_flip"
    assert tiers["corp-content-overwrite"]["difficulty"] == 3
    assert tiers["corp-content-overwrite"]["effect"] == "content_write"


def test_every_corp_tier_carries_an_integer_difficulty_and_a_name():
    for tier in wargames.objectives("corp")["tiers"]:
        assert isinstance(tier["difficulty"], int)
        assert isinstance(tier["name"], str) and tier["name"]
