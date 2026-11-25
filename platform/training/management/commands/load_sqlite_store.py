import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

KEPT_BY_MIGRATE = ("django_migrations",)
NUL = "\x00"
JSON_NUL = "\\u0000"


def migrated_copy(source: Path, scratch: Path) -> Path:
    copy = scratch / "store.sqlite3"
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as read, \
            closing(sqlite3.connect(copy)) as written:
        read.backup(written)
    environ = {**os.environ, "CR_DB_HOST": "", "DJANGO_DB_PATH": str(copy)}
    done = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], env=environ,
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise CommandError(f"the SQLite store could not be migrated to this code: {done.stderr.strip()[-800:]}")
    return copy


def column_types(cursor, table: str) -> list[tuple[str, str]]:
    cursor.execute("SELECT column_name, data_type FROM information_schema.columns "
                   "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", [table])
    return cursor.fetchall()


def without_nul(item):
    if isinstance(item, str):
        return item.replace(NUL, "")
    if isinstance(item, dict):
        return {without_nul(key): without_nul(value) for key, value in item.items()}
    if isinstance(item, list):
        return [without_nul(value) for value in item]
    return item


def json_without_nul(value: str) -> str:
    parsed = json.loads(value, strict=False)
    cleaned = without_nul(parsed)
    return value if cleaned == parsed else json.dumps(cleaned)


def converted(value, kind: str, cleaned: list[int]):
    if value is None:
        return None
    if kind == "boolean":
        return bool(value)
    if kind == "interval" and isinstance(value, int):
        return timedelta(microseconds=value)
    if isinstance(value, str) and kind in ("jsonb", "json") and (NUL in value or JSON_NUL in value):
        loaded = json_without_nul(value)
        cleaned[0] += loaded != value
        return loaded
    if isinstance(value, str) and NUL in value:
        cleaned[0] += 1
        return value.replace(NUL, "")
    return value


def copied(cursor, store: sqlite3.Connection, table: str) -> tuple[int, int]:
    columns = column_types(cursor, table)
    present = {row[1] for row in store.execute(f'PRAGMA table_info("{table}")')}
    taken = [(name, kind) for name, kind in columns if name in present]
    listed = ", ".join(f'"{name}"' for name, _ in taken)
    rows, cleaned = 0, [0]
    with cursor.cursor.copy(f'COPY "{table}" ({listed}) FROM STDIN') as copy:
        for row in store.execute(f'SELECT {listed} FROM "{table}"'):
            copy.write_row([converted(value, kind, cleaned) for value, (_, kind) in zip(row, taken)])
            rows += 1
    return rows, cleaned[0]


def sequences_reset(cursor, tables: list[str]) -> None:
    for table in tables:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND table_name = %s AND (is_identity = 'YES' OR column_default LIKE 'nextval%%')", [table])
        for (column,) in cursor.fetchall():
            cursor.execute(f'SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE(MAX("{column}"), 1), '
                           f'MAX("{column}") IS NOT NULL) FROM "{table}"', [f'"{table}"', column])


class Command(BaseCommand):
    help = ("Load a SQLite store (a db-<UTC stamp>.sqlite3 backup) into this platform's PostgreSQL store, "
            "replacing everything in it. The backup is read, never changed.")

    def add_arguments(self, parser):
        parser.add_argument("backup", type=Path)

    def handle(self, *args, backup: Path, **options):
        if connection.vendor != "postgresql":
            raise CommandError("the platform's store is not PostgreSQL here; set CR_DB_HOST")
        if not backup.is_file():
            raise CommandError(f"{backup} does not exist")
        with tempfile.TemporaryDirectory() as scratch:
            store_path = migrated_copy(backup, Path(scratch))
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
            call_command("migrate", "--noinput", verbosity=0)
            with closing(sqlite3.connect(store_path)) as store:
                self.loaded(store)

    def loaded(self, store: sqlite3.Connection) -> None:
        held = {name for (name,) in store.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        tables = sorted(name for name in connection.introspection.table_names() if name not in KEPT_BY_MIGRATE)
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE " + ", ".join(f'"{name}"' for name in tables) + " RESTART IDENTITY CASCADE")
            for table in tables:
                if table not in held:
                    continue
                rows, cleaned = copied(cursor, store, table)
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                landed = cursor.fetchone()[0]
                if landed != rows:
                    raise CommandError(f"{table}: {rows} rows read, {landed} in PostgreSQL")
                if rows:
                    said = f"{table:<36} {rows:>9}"
                    self.stdout.write(said + (f"  ({cleaned} values lost a NUL character)" if cleaned else ""))
            sequences_reset(cursor, tables)
        self.stdout.write("the SQLite store is loaded into PostgreSQL")
