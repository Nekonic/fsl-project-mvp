import pathlib

import yaml

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _corp():
    return yaml.safe_load((ROOT / "wargames/corp/compose.yaml").read_text())["services"]


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


def test_corp_keeps_no_persistent_volume_so_each_rebuild_is_clean():
    assert not _corp()["corp-db"].get("volumes"), (
        "corp-db declares a persistent volume; a binlog and seeded state would "
        "survive a rebuild and a prior session's change could be replayed"
    )
    assert not _corp()["corp-wp"].get("volumes"), (
        "a wp-content volume would shadow the plugins baked into the image"
    )


def test_corp_is_healthy_only_after_its_forms_and_pages_exist():
    entrypoint = (ROOT / "wargames/corp/app/entrypoint.sh").read_text().splitlines()
    mark = "/tmp/fsl-corp-ready"
    forms = next(i for i, line in enumerate(entrypoint) if "install_default_forms" in line)
    pages = next(i for i, line in enumerate(entrypoint) if "install_default_pages" in line)
    rbsm = next(i for i, line in enumerate(entrypoint) if "fsl-rbsm-form.php" in line)
    touched = [i for i, line in enumerate(entrypoint) if line.startswith("touch ") and mark in line]
    cleared = [i for i, line in enumerate(entrypoint) if line.startswith("rm -f ") and mark in line]
    assert len(touched) == 1 and touched[0] > max(forms, pages, rbsm)
    assert len(cleared) == 1 and cleared[0] < forms
    test = _corp()["corp-wp"]["healthcheck"]["test"]
    assert f"test -f {mark}" in test[-1]
    assert "ultimate-member" in test[-1]
    assert not _corp()["corp-wp"].get("volumes")


def test_a_corp_restored_from_its_pristine_copy_gets_fresh_secret_keys_and_admin_hash():
    entrypoint = (ROOT / "wargames/corp/app/entrypoint.sh").read_text().splitlines()
    removed = entrypoint.index("rm -f /var/www/html/wp-config.php")
    started = next(i for i, line in enumerate(entrypoint) if line.startswith("docker-entrypoint.sh "))
    rehashed = next(i for i, line in enumerate(entrypoint) if "wp user update admin --user_pass=" in line)
    touched = next(i for i, line in enumerate(entrypoint) if line.startswith("touch /tmp/fsl-corp-ready"))
    assert removed < started, (
        "the image's entrypoint writes wp-config.php with new random keys and salts only when it is missing; "
        "a restored volume holds the build's file")
    assert rehashed < touched
