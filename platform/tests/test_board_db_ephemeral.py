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
jiwoo = User.objects.get(username="jiwoo")
print(json.dumps({
    "hashes": {user.username: user.password for user in User.objects.all()},
    "signs_in": {secret: jiwoo.check_password(secret) for secret in ("first-round-secret", "second-round-secret")},
    "posts": Post.objects.count(),
}))
"""


def managing(app):
    def manage(database, *argv, stdin=None):
        env = {"DJANGO_SETTINGS_MODULE": "shim", "BOARD_SQLITE": str(database), "PATH": "/usr/bin:/bin"}
        done = subprocess.run([sys.executable, "manage.py", *argv], cwd=app, env=env, capture_output=True, text=True,
                              input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL, timeout=120)
        assert done.returncode == 0, done.stderr
        return done.stdout

    return manage


def copied_board(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(REPO_ROOT / "wargames/board/app", app)
    (app / "shim.py").write_text(SHIM)
    return app


def test_each_restore_of_the_pristine_board_salts_the_seeded_accounts_afresh(tmp_path):
    manage = managing(copied_board(tmp_path))

    pristine = tmp_path / "pristine.sqlite3"
    manage(pristine, "migrate", "--noinput")
    manage(pristine, "seed")
    built = json.loads(manage(pristine, "shell", "-c", READ).splitlines()[-1])
    restores = []
    for session in ("first", "second"):
        restored = tmp_path / f"{session}.sqlite3"
        shutil.copyfile(pristine, restored)
        manage(restored, "seed")
        manage(restored, "set_passwords", stdin=json.dumps({"jiwoo": f"{session}-round-secret"}))
        restores.append(json.loads(manage(restored, "shell", "-c", READ).splitlines()[-1]))

    first, second = restores
    assert set(first["hashes"]) == {"admin", "jiwoo", "minseo"}
    for name in first["hashes"]:
        assert len({built["hashes"][name], first["hashes"][name], second["hashes"][name]}) == 3, (
            f"{name}: a hash stolen in one session must not match the next session's ground truth")
    assert first["signs_in"] == {"first-round-secret": True, "second-round-secret": False}
    assert second["signs_in"] == {"first-round-secret": False, "second-round-secret": True}, (
        "each round's account signs in with that round's secret only")
    assert first["posts"] == second["posts"] == built["posts"] > 0, "a restored board is not seeded twice"


SIGNS_IN = """import json
from django.contrib.auth.models import User
print(json.dumps({user.username: [user.password, user.check_password(user.username + "1234"),
                                  user.check_password("given-" + user.username)] for user in User.objects.all()}))
"""


def test_set_passwords_gives_the_named_accounts_their_password_and_every_other_account_a_random_one(tmp_path):
    manage = managing(copied_board(tmp_path))
    database = tmp_path / "board.sqlite3"
    manage(database, "migrate", "--noinput")
    manage(database, "seed")
    seeded = json.loads(manage(database, "shell", "-c", SIGNS_IN).splitlines()[-1])

    manage(database, "set_passwords", stdin=json.dumps({"jiwoo": "given-jiwoo", "minseo": "given-minseo"}))
    rotated = json.loads(manage(database, "shell", "-c", SIGNS_IN).splitlines()[-1])

    assert set(rotated) == {"admin", "jiwoo", "minseo"}
    assert all(seeded[name][1] for name in seeded), "the image default still signs in before a round"
    for name, (digest, default_works, given_works) in rotated.items():
        assert digest != seeded[name][0] and not default_works
        assert given_works == (name != "admin")

    manage(database, "set_passwords", stdin=json.dumps({"jiwoo": "given-jiwoo"}))
    next_round = json.loads(manage(database, "shell", "-c", SIGNS_IN).splitlines()[-1])

    assert next_round["admin"][0] != rotated["admin"][0], "the last round's stolen admin hash matches nothing now"
