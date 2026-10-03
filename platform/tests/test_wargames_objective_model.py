import wargames


def test_board_is_loot_verified_and_counts_as_judged():
    assert wargames.objective_model("board") == "loot_verified"
    assert wargames.judged("board") is True


def test_the_catalogue_still_exposes_the_derived_judged_boolean():
    by_id = {w["id"]: w for w in wargames.catalogue()}
    assert by_id["board"]["judged"] is True
