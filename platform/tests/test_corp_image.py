import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "wargames/corp/app"

PLUGINS = {
    "ultimate-member": "2.6.6",
    "wp-gdpr-compliance": "1.4.2",
    "easy-post-submission": "2.3.0",
}


def test_the_image_is_an_official_wordpress_tag():
    dockerfile = (APP / "Dockerfile").read_text()
    assert re.search(r"^FROM wordpress:\S+", dockerfile, re.M), dockerfile


def test_each_plugin_is_pinned_to_its_vulnerable_version():
    text = (APP / "Dockerfile").read_text()
    for slug, version in PLUGINS.items():
        assert re.search(rf"{re.escape(slug)}[/.]{re.escape(version)}\b", text), (slug, version)


def test_the_entrypoint_activates_the_three_plugins_and_leaves_core_registration_off():
    entry = (APP / "entrypoint.sh").read_text()
    for slug in PLUGINS:
        assert f"plugin activate {slug}" in entry or f"--activate" in entry, slug
    assert "users_can_register 0" in entry
    assert "default_role subscriber" in entry


def test_nothing_is_added_to_the_wordpress_app_for_reads():
    assert not (APP / "mu-plugins").exists(), (
        "the platform reads state from the corp-db container, not from a WP "
        "endpoint; nothing is instrumented on the app"
    )


DB = ROOT / "wargames/corp/db"


def test_the_corp_db_base_is_the_boards_database_digest():
    base = re.search(r"^FROM (\S+)$", (DB / "Dockerfile").read_text(), re.M).group(1)
    board = re.search(r"image:\s*(mysql@sha256:\S+)", (ROOT / "wargames/board/compose.yaml").read_text())
    assert "@sha256:" in base, base
    assert board and base == board.group(1), (base, board and board.group(1))


def test_the_corp_db_image_carries_mysqlbinlog_for_the_live_scorer():
    dockerfile = (DB / "Dockerfile").read_text()
    assert "mysql-community-client-8.4" in dockerfile
    assert "/usr/bin/mysqlbinlog" in dockerfile
    assert "rpm -K" in dockerfile, "the downloaded rpm must be signature-checked"


def test_the_corp_db_service_builds_that_image():
    corp_db = yaml.safe_load((ROOT / "wargames/corp/compose.yaml").read_text())["services"]["corp-db"]
    assert corp_db["build"] == "./db"
    assert corp_db["image"] == "fsl/corp-db:mvp"
