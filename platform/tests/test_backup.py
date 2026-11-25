import importlib.util
import io
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

ROOT = Path(__file__).resolve().parents[2]

ROWS = {
    "training_allocation": 3,
    "training_action": 5,
    "telemetry_detection": 7,
    "training_customerrequest": 4,
    "scoring_objective": 2,
    "training_ruleset": 1,
    "training_disabledrule": 0,
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
    monkeypatch.delenv("CR_PLATFORM_EXEC", raising=False)
    monkeypatch.delenv("CR_STORE_EXEC", raising=False)

    def invoke(*asked):
        monkeypatch.setattr(sys, "argv", ["backup", *(asked or ("--sqlite",))])
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


def snapshot_of(module, store):
    image = io.BytesIO()
    module.snapshot(str(store), image)
    return image.getvalue()


def read(image, query):
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(image)
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return db.execute(query).fetchall()


def dump(path):
    with closing(sqlite3.connect(path)) as db:
        return list(db.iterdump())


def answering(monkeypatch, tmp_path, data):
    answer = tmp_path / "answer"
    answer.write_bytes(data)
    monkeypatch.setenv("CR_PLATFORM_EXEC", shlex.join(["cat", str(answer)]))


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
    writer.execute("INSERT INTO training_allocation (note) VALUES ('not committed')")

    image = snapshot_of(backup.module, store)

    writer.execute("COMMIT")
    writer.close()
    assert read(image, "SELECT count(*) FROM training_allocation") == [(3,)]
    assert read(snapshot_of(backup.module, store), "SELECT count(*) FROM training_allocation") == [(4,)], (
        "the snapshot left a lock behind and the platform's next write waited on it")


def test_a_writer_already_writing_into_the_file_is_waited_out_not_copied_half_done(
    backup, tmp_path
):
    store = tmp_path / "db.sqlite3"
    with closing(sqlite3.connect(store)) as db:
        db.execute("CREATE TABLE training_allocation (id INTEGER PRIMARY KEY, label TEXT)")
        db.executemany(
            "INSERT INTO training_allocation (label) VALUES (?)", [("committed",)] * 3000
        )
        db.commit()
    writer = sqlite3.connect(store, isolation_level=None)
    writer.execute("PRAGMA cache_size = 1")
    writer.execute("BEGIN")
    writer.execute("UPDATE training_allocation SET label = printf('%0200d', id)")

    taken = {}
    taking = threading.Thread(
        target=lambda: taken.update(image=snapshot_of(backup.module, store)),
        daemon=True,
    )
    taking.start()
    taking.join(0.5)
    waited = taking.is_alive()
    writer.execute("ROLLBACK")
    writer.close()
    taking.join(10)

    assert waited, "the writer had already spilled into the file, so a copy made now is half its work"
    assert read(taken["image"], "SELECT label, count(*) FROM training_allocation GROUP BY label") == [
        ("committed", 3000)]


def test_a_platform_reached_some_other_way_is_backed_up_the_same(
    backup, tmp_path, monkeypatch
):
    store = made_store(tmp_path / "db.sqlite3")
    monkeypatch.chdir(ROOT / "platform")
    monkeypatch.setenv("DJANGO_DB_PATH", str(store))
    monkeypatch.setenv("CR_DB_HOST", "")
    monkeypatch.setenv("CR_PLATFORM_EXEC", shlex.join([sys.executable, "-"]))

    printed = backup()

    [kept] = backup.module.BACKUPS.iterdir()
    assert re.fullmatch(r"db-\d{8}T\d{6}Z\.sqlite3", kept.name)
    assert str(kept) in printed
    assert dump(kept) == dump(store)


def test_a_database_holding_none_of_the_platform_s_tables_is_not_kept(
    backup, monkeypatch, tmp_path
):
    other = tmp_path / "other.sqlite3"
    with closing(sqlite3.connect(other)) as db:
        db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, note TEXT)")
        db.execute("INSERT INTO notes (note) VALUES ('not the platform')")
        db.commit()
    answering(monkeypatch, tmp_path, other.read_bytes())

    said = failure(backup)

    assert "not the platform's store" in said
    assert backup.kept() == []


@pytest.mark.parametrize("name", ["db-20260925T000000Z.sqlite3", "store-20261126T000000Z.pgdump"])
def test_backups_stay_out_of_git(name):
    listed = load_backup().BACKUPS / name

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(listed.relative_to(ROOT))], cwd=ROOT
    )

    assert ignored.returncode == 0, f"{listed.parent.name}/ is not ignored"


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
        db.execute("CREATE INDEX detection_note ON telemetry_detection (note)")
        db.commit()
        db.execute("PRAGMA writable_schema = ON")
        db.execute("DELETE FROM sqlite_master WHERE name = 'detection_note'")
        db.commit()
    answering(monkeypatch, tmp_path, store.read_bytes())

    said = failure(backup)

    assert "integrity_check" in said
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


def test_a_store_that_keeps_arriving_is_kept_however_long_the_whole_takes(
    backup, monkeypatch, tmp_path
):
    store = made_store(tmp_path / "db.sqlite3")
    size = store.stat().st_size
    monkeypatch.setattr(backup.module, "TIMEOUT", 2.0)
    monkeypatch.setenv("CR_PLATFORM_EXEC", shlex.join([
        "sh", "-c",
        f"for skip in 0 1 2 3 4 5; do sleep 0.5; dd if={shlex.quote(str(store))} bs={size // 6} "
        f"skip=$skip count=1 2>/dev/null; done; "
        f"dd if={shlex.quote(str(store))} bs={size // 6} skip=6 2>/dev/null",
    ]))

    printed = backup()

    assert f"{size} bytes" in printed, (
        "a store of gigabytes takes minutes to cross ssh; only silence is given up on"
    )
    assert dump(backup.module.BACKUPS / backup.kept()[0]) == dump(store)


def test_a_way_in_that_answers_without_reading_the_program_is_still_heard(backup):
    read_end, write_end = os.pipe()
    os.close(read_end)
    stdin = os.fdopen(write_end, "wb")

    backup.module.hand_over(stdin, b"program" * 10000)

    assert stdin.closed, (
        "a command that answers from elsewhere and never reads the program, like the "
        "tests' cat, must not turn the backup into a broken pipe; its output decides"
    )


def test_a_new_backup_leaves_the_newest_keep_and_any_backup_named_by_hand(backup, monkeypatch, tmp_path):
    answering(monkeypatch, tmp_path, made_store(tmp_path / "db.sqlite3").read_bytes())
    backups = backup.module.BACKUPS
    backups.mkdir()
    for name in ("db-20261001T000000Z.sqlite3", "db-20261002T000000Z.sqlite3", "db-20261014-pre-p6.sqlite3"):
        (backups / name).write_bytes(b"older")
    monkeypatch.setattr(sys, "argv", ["backup", "--sqlite", "--keep", "2"])

    backup.module.main()

    left = backup.kept()
    assert "db-20261002T000000Z.sqlite3" in left and "db-20261014-pre-p6.sqlite3" in left and len(left) == 3, (
        f"six 6 GB copies piled up locally; --keep 2 leaves the new one and the newest older one, "
        f"and never a backup someone named by hand: {left}"
    )


def test_the_snapshot_leaves_the_space_of_deleted_rows_behind(backup, tmp_path):
    store = made_store(tmp_path / "db.sqlite3")
    with closing(sqlite3.connect(store)) as db:
        db.executemany("INSERT INTO telemetry_detection (note) VALUES (?)", [("x" * 1000,)] * 2000)
        db.commit()
        db.execute("DELETE FROM telemetry_detection")
        db.commit()

    image = snapshot_of(backup.module, store)

    assert len(image) < store.stat().st_size / 10, (
        "pruned allocations leave free pages in the store; shipping them made every rebuild copy 6 GB"
    )


def test_a_backup_of_an_empty_store_removes_no_older_backup(backup, monkeypatch, tmp_path):
    empty = tmp_path / "empty.sqlite3"
    with closing(sqlite3.connect(empty)) as db:
        for table in ROWS:
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, note TEXT)")
        db.commit()
    answering(monkeypatch, tmp_path, empty.read_bytes())
    backups = backup.module.BACKUPS
    backups.mkdir()
    (backups / "db-20261001T000000Z.sqlite3").write_bytes(b"older")

    said = backup()

    assert backup.kept() == ["db-20261001T000000Z.sqlite3"], (
        "a replacement VM that never took its hand-over holds a new, empty store; backing it up "
        "with --keep 1 removed the only copy of the store it was meant to receive"
    )
    assert "holds no rows" in said


@pytest.mark.parametrize("answer", [b"", b"Traceback (most recent call last):\n", b"SQLite format 3\x00"],
                         ids=["nothing", "text", "a-sqlite-file"])
def test_an_answer_that_is_not_a_pg_dump_archive_is_not_kept(backup, monkeypatch, tmp_path, answer):
    given = tmp_path / "answer"
    given.write_bytes(answer)
    monkeypatch.setenv("CR_STORE_EXEC", shlex.join(["cat", str(given)]))

    said = failure(lambda: backup("--keep", "1"))

    assert "pg_dump" in said
    assert backup.kept() == []


def test_a_new_archive_thins_the_older_backups_of_both_kinds_by_their_stamp(backup, monkeypatch, tmp_path):
    backups = backup.module.BACKUPS
    backups.mkdir()
    for name in ("db-20261001T000000Z.sqlite3", "db-20261002T000000Z.sqlite3", "store-20261003T000000Z.pgdump",
                 "db-20261014-pre-p6.sqlite3"):
        (backups / name).write_bytes(b"older")
    kept = backups / "store-20261126T000000Z.pgdump"
    kept.write_bytes(b"PGDMP")

    gone = backup.module.thin(kept, 2)

    assert [path.name for path in gone] == ["db-20261001T000000Z.sqlite3", "db-20261002T000000Z.sqlite3"]
    assert backup.kept() == ["db-20261014-pre-p6.sqlite3", "store-20261003T000000Z.pgdump", kept.name]
