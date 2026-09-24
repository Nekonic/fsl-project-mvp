import importlib.util
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from django.apps import apps

ROOT = Path(__file__).resolve().parents[2]

ROWS = {
    "api_session": 3,
    "api_case": 5,
    "api_detection": 7,
    "api_objective": 2,
    "api_ruleset": 1,
    "api_suppression": 0,
}


def load_backup():
    loader = SourceFileLoader("backup", str(ROOT / "bin/backup"))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("backup", loader)
    )
    loader.exec_module(module)
    return module


@pytest.fixture
def backup(tmp_path, monkeypatch, capsys):
    module = load_backup()
    backups = tmp_path / "backups"
    monkeypatch.setattr(module, "BACKUPS", backups)
    monkeypatch.delenv("FSL_PLATFORM_EXEC", raising=False)

    def invoke():
        monkeypatch.setattr(sys, "argv", ["backup"])
        module.main()
        return capsys.readouterr().out

    def kept():
        return sorted(path.name for path in backups.iterdir()) if backups.exists() else []

    invoke.module = module
    invoke.kept = kept
    return invoke


def made_store(path):
    with closing(sqlite3.connect(path)) as db:
        for table, count in ROWS.items():
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, note TEXT)")
            db.executemany(
                f"INSERT INTO {table} (note) VALUES (?)",
                [(f"{table} {n}",) for n in range(count)],
            )
        db.commit()
    return path


def opened(image):
    db = sqlite3.connect(":memory:")
    db.deserialize(image)
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    return db


def dump(path):
    with closing(sqlite3.connect(path)) as db:
        return list(db.iterdump())


def answering(monkeypatch, tmp_path, data):
    answer = tmp_path / "answer"
    answer.write_bytes(data)
    monkeypatch.setenv("FSL_PLATFORM_EXEC", shlex.join(["cat", str(answer)]))


def failure(backup):
    with pytest.raises(SystemExit) as failed:
        backup()
    assert isinstance(failed.value.code, str) and failed.value.code, (
        "SystemExit with a message exits 1 and says why; anything else can "
        "look like success to a script that runs this"
    )
    return failed.value.code


def test_a_writer_holding_a_transaction_open_is_neither_waited_for_nor_copied(
    backup, tmp_path
):
    store = made_store(tmp_path / "db.sqlite3")
    writer = sqlite3.connect(store, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO api_session (note) VALUES ('not committed')")

    image = backup.module.snapshot(str(store))

    writer.execute("COMMIT")
    writer.close()
    assert opened(image).execute("SELECT count(*) FROM api_session").fetchone() == (3,)
    assert opened(backup.module.snapshot(str(store))).execute(
        "SELECT count(*) FROM api_session"
    ).fetchone() == (4,), "the snapshot left a lock behind and the platform's next write waited on it"


def test_a_writer_already_writing_into_the_file_is_waited_out_not_copied_half_done(
    backup, tmp_path
):
    store = tmp_path / "db.sqlite3"
    with closing(sqlite3.connect(store)) as db:
        db.execute("CREATE TABLE api_session (id INTEGER PRIMARY KEY, scenario TEXT)")
        db.executemany(
            "INSERT INTO api_session (scenario) VALUES (?)", [("committed",)] * 3000
        )
        db.commit()
    writer = sqlite3.connect(store, isolation_level=None)
    writer.execute("PRAGMA cache_size = 1")
    writer.execute("BEGIN")
    writer.execute("UPDATE api_session SET scenario = printf('%0200d', id)")

    taken = {}
    taking = threading.Thread(
        target=lambda: taken.update(image=backup.module.snapshot(str(store))),
        daemon=True,
    )
    taking.start()
    taking.join(0.5)
    waited = taking.is_alive()
    writer.execute("ROLLBACK")
    writer.close()
    taking.join(10)

    assert waited, "the writer had already spilled into the file, so a copy made now is half its work"
    assert opened(taken["image"]).execute(
        "SELECT scenario, count(*) FROM api_session GROUP BY scenario"
    ).fetchall() == [("committed", 3000)]


def test_a_platform_reached_some_other_way_is_backed_up_the_same(
    backup, tmp_path, monkeypatch
):
    store = made_store(tmp_path / "db.sqlite3")
    monkeypatch.chdir(ROOT / "platform")
    monkeypatch.setenv("DJANGO_DB_PATH", str(store))
    monkeypatch.setenv("FSL_PLATFORM_EXEC", shlex.join([sys.executable, "-"]))

    printed = backup()

    [kept] = backup.module.BACKUPS.iterdir()
    assert re.fullmatch(r"db-\d{8}T\d{6}Z\.sqlite3", kept.name)
    assert str(kept) in printed
    assert dump(kept) == dump(store)
    for label, table in backup.module.TABLES:
        assert re.search(rf"^\s*{label}\s+{ROWS[table]}$", printed, re.M), (
            f"{label} should read {ROWS[table]}:\n{printed}"
        )


@pytest.mark.stands_in_for_docker
def test_by_default_the_snapshot_runs_inside_the_platform_container(
    backup, tmp_path, monkeypatch
):
    store = made_store(tmp_path / "db.sqlite3")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(tmp_path / 'argv'))}\n"
        f"cat > {shlex.quote(str(tmp_path / 'program'))}\n"
        f"exec cat {shlex.quote(str(store))}\n"
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    backup()

    assert (tmp_path / "argv").read_text().split() == [
        "exec", "-i", "fsl-platform", "python", "-",
    ]
    assert "def snapshot(" in (tmp_path / "program").read_text()
    assert len(backup.kept()) == 1 and backup.kept()[0].endswith(".sqlite3")


def test_every_table_the_platform_keeps_is_counted(backup):
    stored = {model._meta.db_table for model in apps.get_app_config("api").get_models()}

    assert {table for _, table in backup.module.TABLES} == stored


def test_backups_stay_out_of_git():
    listed = load_backup().BACKUPS / "db-20260925T000000Z.sqlite3"

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(listed.relative_to(ROOT))], cwd=ROOT
    )

    assert ignored.returncode == 0, f"{listed.parent.name}/ is not ignored"


def test_a_platform_that_is_down_is_reported_in_docker_s_own_words(
    backup, monkeypatch, tmp_path
):
    docker_said = tmp_path / "stderr"
    docker_said.write_text("Error response from daemon: No such container: fsl-platform\n")
    monkeypatch.setenv("FSL_PLATFORM_EXEC", shlex.join([
        "sh", "-c", f"cat {shlex.quote(str(docker_said))} >&2; exit 1",
    ]))

    said = failure(backup)

    assert "No such container: fsl-platform" in said
    assert backup.kept() == []


def test_a_way_in_that_cannot_be_started_names_the_variable_that_chooses_it(
    backup, monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "FSL_PLATFORM_EXEC", f"{tmp_path / 'no-such-docker'} exec -i fsl-platform python -"
    )

    said = failure(backup)

    assert "FSL_PLATFORM_EXEC" in said
    assert backup.kept() == []


@pytest.mark.parametrize("answer", [
    b"",
    b"Traceback (most recent call last):\n",
    b"a warning printed ahead of the image\nSQLite format 3\x00",
], ids=["nothing", "text", "text-before-the-image"])
def test_an_answer_that_is_not_the_store_is_not_kept(
    backup, monkeypatch, tmp_path, answer
):
    answering(monkeypatch, tmp_path, answer)

    failure(backup)

    assert backup.kept() == []


def test_a_snapshot_failing_integrity_check_is_not_kept(backup, monkeypatch, tmp_path):
    store = made_store(tmp_path / "db.sqlite3")
    with closing(sqlite3.connect(store)) as db:
        db.execute("CREATE INDEX detection_note ON api_detection (note)")
        db.commit()
        db.execute("PRAGMA writable_schema = ON")
        db.execute("DELETE FROM sqlite_master WHERE name = 'detection_note'")
        db.commit()
    answering(monkeypatch, tmp_path, store.read_bytes())

    said = failure(backup)

    assert "integrity_check" in said
    assert backup.kept() == []


def test_a_snapshot_that_is_too_slow_to_arrive_is_given_up_on(
    backup, monkeypatch, tmp_path
):
    store = made_store(tmp_path / "db.sqlite3")
    monkeypatch.setattr(backup.module, "TIMEOUT", 0.5)
    monkeypatch.setenv("FSL_PLATFORM_EXEC", shlex.join([
        "sh", "-c", f"sleep 5; exec cat {shlex.quote(str(store))}",
    ]))

    said = failure(backup)

    assert "0.5s" in said
    assert backup.kept() == []


def test_nothing_is_named_like_a_backup_until_it_has_passed_the_check(
    backup, monkeypatch, tmp_path
):
    answering(monkeypatch, tmp_path, made_store(tmp_path / "db.sqlite3").read_bytes())
    present_while_checking = []
    check = backup.module.check

    def watched(path):
        present_while_checking.extend(entry.name for entry in path.parent.iterdir())
        return check(path)

    monkeypatch.setattr(backup.module, "check", watched)

    backup()

    assert present_while_checking
    assert not [name for name in present_while_checking if name.endswith(".sqlite3")]
    assert len(backup.kept()) == 1 and backup.kept()[0].endswith(".sqlite3")


def test_a_store_kept_in_wal_mode_is_checked_without_litter_beside_the_backup(
    backup, monkeypatch, tmp_path
):
    store = made_store(tmp_path / "db.sqlite3")
    with closing(sqlite3.connect(store)) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("INSERT INTO api_session (note) VALUES ('after the switch')")
        db.commit()
    answering(monkeypatch, tmp_path, backup.module.snapshot(str(store)))

    printed = backup()

    assert re.search(r"^\s*sessions\s+4$", printed, re.M), printed
    assert len(backup.kept()) == 1 and backup.kept()[0].endswith(".sqlite3"), (
        f"opening the check read-write on a WAL image leaves its -wal and -shm "
        f"behind: {backup.kept()}"
    )
