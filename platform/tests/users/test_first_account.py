import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from django.contrib.auth import authenticate, get_user_model

ROOT = Path(__file__).resolve().parents[3]


def test_a_migrated_store_holds_admin_as_active_staff_who_signs_in_with_123456(db):
    admin = get_user_model().objects.get(username="admin")

    assert admin.is_staff and admin.is_active
    assert authenticate(username="admin", password="123456") == admin


def test_a_fresh_store_gets_the_first_account_from_migrate_alone(tmp_path):
    store = tmp_path / "fresh.sqlite3"
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=ROOT / "platform", check=True,
                   capture_output=True, env={**os.environ, "DJANGO_DB_PATH": str(store)})

    with sqlite3.connect(store) as opened:
        assert opened.execute("select username, is_staff, is_active from auth_user").fetchall() == [("admin", 1, 1)]
