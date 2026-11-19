import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CARRY = ROOT / "bin" / "carry-users"
ROWS = "select username, password, is_active, is_staff, is_superuser from auth_user order by id"


def manage(store: Path, *arguments: str) -> None:
    subprocess.run([sys.executable, "manage.py", *arguments], cwd=ROOT / "platform", check=True,
                   capture_output=True, env={**os.environ, "DJANGO_DB_PATH": str(store)})


def carry(old: Path, new: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CARRY), "--from", str(old), "--into", str(new)],
                          capture_output=True, text=True)


@pytest.fixture
def old_store(tmp_path):
    store = tmp_path / "old.sqlite3"
    manage(store, "migrate", "--noinput", "auth")
    old = sqlite3.connect(store)
    with old:
        old.execute("insert into django_content_type (app_label, model) values ('retired', 'session')")
        kind = old.execute("select id from django_content_type where app_label = 'retired'").fetchone()[0]
        old.execute("insert into auth_permission (name, content_type_id, codename) values ('x', ?, 'run_retired')",
                    (kind,))
        permission = old.execute("select id from auth_permission where codename = 'run_retired'").fetchone()[0]
        for username, active, staff in (("admin", 1, 1), ("learner", 1, 0), ("waiting", 0, 0)):
            old.execute("insert into auth_user (password, is_superuser, username, first_name, last_name, email, "
                        "is_staff, is_active, date_joined) values (?, ?, ?, '', '', '', ?, ?, '2026-11-01 00:00:00')",
                        (f"pbkdf2_sha256$1$salt${username}", staff, username, staff, active))
        learner = old.execute("select id from auth_user where username = 'learner'").fetchone()[0]
        old.execute("insert into auth_user_user_permissions (user_id, permission_id) values (?, ?)",
                    (learner, permission))
        old.execute("create table retired_session (id integer primary key)")
    old.close()
    return store


def rows(store: Path) -> list[tuple]:
    opened = sqlite3.connect(store)
    try:
        return opened.execute(ROWS).fetchall()
    finally:
        opened.close()


def test_users_carry_over_with_their_password_hashes_approval_and_staff_flags(old_store, tmp_path):
    new = tmp_path / "new.sqlite3"
    before = old_store.read_bytes()

    done = carry(old_store, new)

    assert done.returncode == 0, done.stderr
    assert "carried 3 users (1 staff, 1 waiting for approval)" in done.stdout
    assert rows(new) == rows(old_store)
    assert old_store.read_bytes() == before, "the old store is read from a copy and never written"
    with sqlite3.connect(new) as opened:
        assert opened.execute("select count(*) from auth_user_user_permissions").fetchone() == (0,)
        assert "accounts_signinblock" in {name for (name,) in opened.execute(
            "select name from sqlite_master where type = 'table'")}


def test_a_store_that_already_holds_users_is_refused(old_store, tmp_path):
    new = tmp_path / "new.sqlite3"
    assert carry(old_store, new).returncode == 0

    again = carry(old_store, new)

    assert again.returncode != 0 and "already holds users" in again.stderr
