import pytest

from shared_sessions import DEFACED, POST_FIELDS, corp_is_declared


@pytest.fixture
def corp_stands(stack_is_up):
    corp_is_declared()


def test_a_live_rogue_admin_is_credited_from_the_targets_own_row_with_no_signature(
    corp_stands, rogue_admin_session
):
    seen = rogue_admin_session
    assert seen["admins_left"] == seen["baseline"], (
        f"left corp-db dirty: admins now {sorted(seen['admins_left'])}, "
        f"baseline {sorted(seen['baseline'])}"
    )
    assert seen["code"] == "302", f"the rogue-admin registration did not complete, got {seen['code']!r}"
    assert seen["created"] and all(uid > 1 for uid in seen["created"]), (
        f"no non-baseline administrator was committed; admins {sorted(seen['admins'])}"
    )
    assert seen["observed"]["total"] == 3, seen["observed"]

    assert seen["credited"] == {"corp-rogue-admin", "corp-content-overwrite"}, (
        f"the target's own rows credited {seen['credited']}, not exactly the two breaches the session made"
    )

    score = seen["score"]
    breach = next((b for b in score["breaches"] if b["key"] == "corp-rogue-admin"), None)
    assert breach is not None, score["breaches"]
    assert breach["detected"] is False, breach
    assert breach["detection_ids"] == [], breach
    assert score["objectives"]["objectives"] >= 1, score["objectives"]


def test_a_live_content_overwrite_is_credited_from_the_targets_own_row(corp_stands, rogue_admin_session):
    seen = rogue_admin_session
    assert '"success":true' in seen["overwrite"], f"the postId overwrite was refused: {seen['overwrite']!r}"
    assert (seen["overwritten"]["post_title"], seen["overwritten"]["post_content"]) == (
        DEFACED["post_title"], DEFACED["post_content"]), seen["overwritten"]

    assert "corp-content-overwrite" in seen["credited"]
    assert "corp-content-overwrite" in {b["key"] for b in seen["score"]["breaches"]}, seen["score"]["breaches"]

    assert seen["restored"] == {field: seen["original"][field] for field in POST_FIELDS}, seen["restored"]


def test_a_live_option_flip_is_credited_from_the_targets_own_row(corp_stands, option_flip_session):
    seen = option_flip_session
    assert seen["options_left"] == ("0", "subscriber"), seen["options_left"]
    assert seen["flips"] == ("200", "200"), seen["flips"]
    assert seen["registration_open"] == "1"
    assert seen["observed"]["total"] == 3, seen["observed"]

    assert seen["credited"] == {"corp-self-registration"}, (
        f"the binlog read did not credit the option flip alone; got {seen['credited']}"
    )
    assert "corp-self-registration" in {b["key"] for b in seen["score"]["breaches"]}, seen["score"]["breaches"]
