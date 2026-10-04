import pathlib
import re

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
