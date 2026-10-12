def test_a_live_rogue_admin_registration_is_scored_from_the_targets_own_binlog(rogue_admin_session):
    seen = rogue_admin_session
    assert seen["admins_left"] == seen["baseline"], (
        f"left corp-db dirty: admins now {sorted(seen['admins_left'])}, "
        f"baseline {sorted(seen['baseline'])}"
    )
    assert seen["code"] == "302", f"the rogue-admin registration did not complete, got {seen['code']!r}"
    assert seen["created"] and all(uid > 1 for uid in seen["created"]), (
        f"no non-baseline administrator was committed; admins {sorted(seen['admins'])}"
    )
    assert seen["observed"]["total"] == 3

    assert seen["credited"] == {"corp-rogue-admin"}, (
        f"the binlog read did not credit the rogue admin; got {seen['credited']}"
    )

    score = seen["score"]
    assert score["objectives"]["objectives"] >= 1
    assert "corp-rogue-admin" in {b["key"] for b in score["breaches"]}


def test_a_live_option_flip_is_scored_from_the_targets_own_binlog(option_flip_session):
    seen = option_flip_session
    assert seen["options_left"] == ("0", "subscriber"), seen["options_left"]
    assert seen["flips"] == ("200", "200"), seen["flips"]
    assert seen["registration_open"] == "1"

    assert seen["credited"] == {"corp-self-registration"}, (
        f"the binlog read did not credit the option flip; got {seen['credited']}"
    )
    assert "corp-self-registration" in {b["key"] for b in seen["score"]["breaches"]}
