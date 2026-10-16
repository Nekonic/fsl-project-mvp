from datetime import timedelta, timezone
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("binlog, options, tier", [
    ("corp-rogue-admin.binlog", {}, "corp-rogue-admin"),
    ("corp-option-flip.binlog", {"users_can_register": "0"}, "corp-self-registration"),
    ("corp-content-write.binlog", {}, "corp-content-overwrite"),
])
def test_credited_fires_each_effect_against_the_baseline(binlog, options, tier):
    baseline = {"admins": [1], "options": options, "posts": [1]}
    assert tier in _credited(binlog, baseline)


def test_credited_stays_silent_when_the_change_matches_the_baseline():
    baseline = {
        "admins": [1],
        "options": {"users_can_register": "1", "default_role": "administrator"},
        "posts": [1],
    }
    assert "corp-self-registration" not in _credited("corp-option-flip.binlog", baseline)


def test_changes_before_the_since_mark_are_dropped():
    changes = _parse("corp-option-flip.binlog")
    assert changes
    latest = max(c.at for c in changes)
    assert _parse("corp-option-flip.binlog", since=latest + timedelta(seconds=1)) == []


def test_each_change_carries_the_timestamp_of_its_own_transaction():
    changes = _parse("corp-option-flip.binlog")
    flip = next(
        c for c in changes
        if c.columns.get(effect.COLUMNS["wp_options"]["option_name"]) == "users_can_register"
    )
    assert flip.at.tzinfo == timezone.utc
    assert flip.at.timestamp() == 1791109664
    assert changes[-1].at.timestamp() == 1791109674
    assert sorted({c.at.timestamp() for c in changes}) == [1791109664, 1791109666, 1791109674]


def _post_row(post_id, kind, status, post_type):
    verb = {"insert": "INSERT INTO", "update": "UPDATE"}[kind]
    image = {1: post_id, 8: f"'{status}'", 21: f"'{post_type}'", 6: "'t'", 5: "'x'"}
    cells = "\n".join(f"###   @{n}={image.get(n, 0)}" for n in range(1, 24))
    section = "SET" if kind == "insert" else "WHERE\n" + cells + "\n### SET"
    return (
        "SET TIMESTAMP=1791112159/*!*/;\n"
        f"### {verb} `wordpress`.`wp_posts`\n### {section}\n{cells}\n"
    )


def _credited_posts(text, posts=(1,)):
    baseline = {"admins": [1], "options": {}, "posts": list(posts)}
    return {tier["key"] for tier, _ in effect.credited(SPEC, baseline, effect.parse_binlog(text))}


def test_credited_takes_nothing_without_a_snapshot():
    for blind in (None, {}, []):
        for name in ("corp-rogue-admin.binlog", "corp-option-flip.binlog", "corp-content-write.binlog"):
            assert _credited(name, blind) == set()


@pytest.mark.parametrize("post_id, kind, status, post_type, credited", [
    (40, "insert", "inherit", "revision", set()),
    (41, "insert", "auto-draft", "post", set()),
    (1, "update", "inherit", "revision", set()),
    (42, "insert", "publish", "post", {"corp-content-overwrite"}),
    (43, "insert", "draft", "post", {"corp-content-overwrite"}),
    (1, "update", "publish", "post", {"corp-content-overwrite"}),
])
def test_a_published_or_draft_post_is_a_content_write(post_id, kind, status, post_type, credited):
    assert _credited_posts(_post_row(post_id, kind, status, post_type)) == credited
