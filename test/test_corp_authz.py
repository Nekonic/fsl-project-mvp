import pytest

from shared_rounds import DEFACED, corp_is_declared


@pytest.fixture
def corp_stands(stack_is_up):
    corp_is_declared()


def lost_in(score: dict) -> dict[str, dict]:
    return {line["key"]: line for line in score["objectives"]["lost"]}


def test_a_live_rogue_admin_is_lost_from_the_targets_own_row_and_detected(corp_stands, rogue_admin_round):
    seen = rogue_admin_round
    assert seen["registered"].ok and seen["registered"].body["status"] == 302, (
        f"the rogue-admin registration did not complete: {seen['registered'].text}")
    assert seen["created"] and all(uid > 1 for uid in seen["created"]), (
        f"no non-baseline administrator was committed; admins {sorted(seen['admins'])}"
    )

    assert seen["lost"] == {"corp-rogue-admin", "corp-content-overwrite"}, (
        f"the target's own rows lost {seen['lost']}, not exactly the two breaches the round made"
    )

    breach = lost_in(seen["score"]).get("corp-rogue-admin")
    assert breach is not None, seen["score"]["objectives"]
    assert breach["detected"] is True, breach
    assert breach["attributed_marker"], f"the breach was tied to no action of the attack player: {breach}"


def test_a_live_content_overwrite_is_lost_from_the_targets_own_row(corp_stands, rogue_admin_round):
    seen = rogue_admin_round
    assert '"success":true' in seen["overwrite"].body["body"], (
        f"the postId overwrite was refused: {seen['overwrite'].text}")
    assert (seen["overwritten"]["post_title"], seen["overwritten"]["post_content"]) == (
        DEFACED["post_title"], DEFACED["post_content"]), seen["overwritten"]

    assert "corp-content-overwrite" in lost_in(seen["score"]), seen["score"]["objectives"]


def test_a_live_option_flip_is_lost_from_the_targets_own_row(corp_stands, option_flip_round):
    seen = option_flip_round
    assert seen["flips"] == (200, 200), seen["flips"]
    assert seen["registration_open"] == "1"

    assert seen["lost"] - {"corp-rogue-admin"} == {"corp-self-registration"}, (
        f"the target's own record did not lose the option flip; got {seen['lost']}"
    )
    lost = lost_in(seen["score"])
    assert "corp-self-registration" in lost, seen["score"]["objectives"]
    if "corp-rogue-admin" in lost:
        assert lost["corp-rogue-admin"]["attributed_marker"] in seen["flip_markers"], (
            f"an administrator the flip did not make was counted: {lost['corp-rogue-admin']}")
