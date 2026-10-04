from datetime import timedelta, timezone
from pathlib import Path

from api import effect

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SPEC = {
    "tiers": [
        {"key": "corp-rogue-admin", "name": "r", "difficulty": 5, "effect": "rogue_admin"},
        {"key": "corp-self-registration", "name": "s", "difficulty": 4, "effect": "option_flip"},
        {"key": "corp-content-overwrite", "name": "c", "difficulty": 3, "effect": "content_write"},
    ]
}


def _parse(name, **kwargs):
    return effect.parse_binlog((FIXTURES / name).read_text(), **kwargs)


def _credited(name, baseline):
    return {tier["key"] for tier, _ in effect.credited(SPEC, baseline, _parse(name))}


def test_credited_fires_rogue_admin_for_a_grant_to_a_non_baseline_user():
    baseline = {"admins": [1], "options": {}, "posts": [1]}
    assert "corp-rogue-admin" in _credited("corp-rogue-admin.binlog", baseline)


def test_credited_fires_option_flip_against_the_baseline_options():
    baseline = {"admins": [1], "options": {"users_can_register": "0"}, "posts": [1]}
    assert "corp-self-registration" in _credited("corp-option-flip.binlog", baseline)


def test_credited_fires_content_write_for_an_overwrite_of_a_baseline_post():
    baseline = {"admins": [1], "options": {}, "posts": [1]}
    assert "corp-content-overwrite" in _credited("corp-content-write.binlog", baseline)


def test_credited_stays_silent_when_the_change_matches_the_baseline():
    baseline = {
        "admins": [1],
        "options": {"users_can_register": "1", "default_role": "administrator"},
        "posts": [1],
    }
    assert "corp-self-registration" not in _credited("corp-option-flip.binlog", baseline)


def test_the_rogue_admin_binlog_shows_a_usermeta_admin_grant():
    changes = _parse("corp-rogue-admin.binlog")
    grants = [
        c for c in changes
        if c.table == "wp_usermeta"
        and c.columns.get(effect.COLUMNS["wp_usermeta"]["meta_key"]) == "wp_capabilities"
        and "administrator" in (c.columns.get(effect.COLUMNS["wp_usermeta"]["meta_value"]) or "")
    ]
    assert grants
    assert grants[0].at.tzinfo == timezone.utc


def test_the_option_flip_binlog_shows_users_can_register_going_to_one():
    changes = _parse("corp-option-flip.binlog")
    flips = [
        c for c in changes
        if c.table == "wp_options"
        and c.columns.get(effect.COLUMNS["wp_options"]["option_name"]) == "users_can_register"
        and c.columns.get(effect.COLUMNS["wp_options"]["option_value"]) == "1"
    ]
    assert flips


def test_the_content_write_binlog_shows_a_new_post_row():
    changes = _parse("corp-content-write.binlog")
    assert any(c.table == "wp_posts" and c.kind in {"insert", "update"} for c in changes)


def test_changes_before_the_since_mark_are_dropped():
    changes = _parse("corp-option-flip.binlog")
    assert changes
    latest = max(c.at for c in changes)
    assert _parse("corp-option-flip.binlog", since=latest + timedelta(seconds=1)) == []


def test_an_update_keeps_the_after_image_not_the_before_image():
    posts = [c for c in _parse("corp-content-write.binlog") if c.table == "wp_posts"]
    assert len(posts) == 1
    columns = posts[0].columns
    assert columns[effect.COLUMNS["wp_posts"]["post_title"]] == "Defaced by an unauthenticated guest"
    assert "overwritten" in columns[effect.COLUMNS["wp_posts"]["post_content"]]


def test_a_delete_keeps_the_row_that_was_removed():
    deletes = [c for c in _parse("corp-option-flip.binlog") if c.kind == "delete"]
    assert deletes
    assert deletes[0].table == "wp_options"
    assert deletes[0].columns.get(effect.COLUMNS["wp_options"]["option_name"])


def test_each_change_carries_the_timestamp_of_its_own_transaction():
    changes = _parse("corp-option-flip.binlog")
    flip = next(
        c for c in changes
        if c.columns.get(effect.COLUMNS["wp_options"]["option_name"]) == "users_can_register"
    )
    assert flip.at.timestamp() == 1791109664
    assert changes[-1].at.timestamp() == 1791109674
    assert sorted({c.at.timestamp() for c in changes}) == [1791109664, 1791109666, 1791109674]
