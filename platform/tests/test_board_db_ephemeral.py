import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_board_db_keeps_no_persistent_volume_so_salts_rotate_on_rebuild():
    compose = yaml.safe_load((REPO_ROOT / "wargames/board/compose.yaml").read_text())
    board_db = compose["services"]["board-db"]
    assert not board_db.get("volumes"), (
        "board-db declares a persistent volume; its MySQL data would survive a "
        "rebuild, so the seeded password salts would not rotate and a dump from a "
        "prior session could be replayed against the next"
    )
