import json
import pathlib
import shutil
import subprocess
import sys

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


SHIM = """from board.settings import *
import os
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ["BOARD_SQLITE"]}}
MIDDLEWARE = [entry for entry in MIDDLEWARE if "whitenoise" not in entry]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
"""

READ = """import json
from django.contrib.auth.models import User
from posts.models import Post
print(json.dumps({
    "hashes": {user.username: user.password for user in User.objects.all()},
    "valid": all(User.objects.get(username=name).check_password(name + "1234") for name in ("jiwoo", "minseo")),
    "posts": Post.objects.count(),
}))
"""


def test_each_restore_of_the_pristine_board_salts_the_seeded_accounts_afresh(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(REPO_ROOT / "wargames/board/app", app)
    (app / "shim.py").write_text(SHIM)

    def manage(database, *argv):
        env = {"DJANGO_SETTINGS_MODULE": "shim", "BOARD_SQLITE": str(database), "PATH": "/usr/bin:/bin"}
        done = subprocess.run([sys.executable, "manage.py", *argv], cwd=app, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        assert done.returncode == 0, done.stderr
        return done.stdout

    pristine = tmp_path / "pristine.sqlite3"
    manage(pristine, "makemigrations", "posts", "--noinput")
    manage(pristine, "migrate", "--noinput")
    manage(pristine, "seed")
    built = json.loads(manage(pristine, "shell", "-c", READ).splitlines()[-1])
    restores = []
    for session in ("first", "second"):
        restored = tmp_path / f"{session}.sqlite3"
        shutil.copyfile(pristine, restored)
        manage(restored, "seed")
        restores.append(json.loads(manage(restored, "shell", "-c", READ).splitlines()[-1]))

    first, second = restores
    assert set(first["hashes"]) == {"admin", "jiwoo", "minseo"}
    for name in first["hashes"]:
        assert len({built["hashes"][name], first["hashes"][name], second["hashes"][name]}) == 3, (
            f"{name}: a hash stolen in one session must not match the next session's ground truth")
    assert first["valid"] and second["valid"], "the seeded passwords still log in"
    assert first["posts"] == second["posts"] == built["posts"] > 0, "a restored board is not seeded twice"
