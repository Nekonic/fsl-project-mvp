import pathlib

import yaml

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _corp():
    return yaml.safe_load((ROOT / "wargames/corp/compose.yaml").read_text())["services"]


def test_corp_is_one_folder_the_session_stack_includes():
    included = [str(p.relative_to(composed.ROOT)) for p in composed.included()]
    assert "wargames/corp/compose.yaml" in included


def test_corp_wp_and_db_stand_inside_the_estate_only_and_publish_nothing():
    services = composed.services()
    for name in ("corp-wp", "corp-db"):
        joined = services[name].get("networks") or []
        assert (joined if isinstance(joined, list) else sorted(joined)) == ["estate"], name
        assert not services[name].get("ports"), f"{name} is published past the WAF"


def test_corp_db_logs_every_committed_row_change():
    command = " ".join(_corp()["corp-db"].get("command") or [])
    assert "--binlog-format=ROW" in command
    assert "--log-bin" in command


def test_corp_db_keeps_no_persistent_volume_so_each_rebuild_is_clean():
    assert not _corp()["corp-db"].get("volumes"), (
        "corp-db declares a persistent volume; a binlog and seeded state would "
        "survive a rebuild and a prior session's change could be replayed"
    )


def test_corp_wp_does_not_keep_wp_content_on_a_volume():
    assert not _corp()["corp-wp"].get("volumes"), (
        "a wp-content volume would shadow the plugins baked into the image"
    )
