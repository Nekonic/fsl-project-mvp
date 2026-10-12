BASELINE_ADMINS = {1}


def test_the_rogue_admin_registration_commits_a_new_administrator(rogue_admin_session):
    seen = rogue_admin_session
    assert seen["code"] == "302", f"registration did not complete, got {seen['code']!r}"
    assert seen["created"], "no new administrator was committed by the UM rogue-admin registration"
    assert all(uid > 1 for uid in seen["created"]), (
        f"expected a non-baseline administrator (id > 1), got {sorted(seen['created'])}"
    )
    assert seen["admins_left"] == BASELINE_ADMINS
