import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "services:\n  web:\n    image: nginx:1.27\n"


def git(root, *argv):
    return subprocess.run(
        ["git", *argv], cwd=root, check=True, capture_output=True
    ).stdout


def write(root, path, text=""):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    write(root, "compose.yaml", COMPOSE)
    (root / "bin").mkdir()
    shutil.copy(ROOT / "bin/measure", root / "bin/measure")
    git(root, "init", "-q")
    return root


def run_measure(root):
    return subprocess.run(
        [sys.executable, "-S", str(root / "bin/measure"), "--json"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )


def measured(root):
    done = run_measure(root)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_tracked_file_missing_from_disk_is_skipped_not_a_crash(repo):
    write(repo, "platform/scoring/before.py", "a = 1\nb = 2\n")
    git(repo, "add", ".")
    (repo / "platform/scoring/before.py").rename(repo / "platform/scoring/after.py")
    git(repo, "add", "platform/scoring/after.py")

    assert measured(repo)["core_loc"] == 2, (
        "a rename staged as mv plus git add leaves the old path in the index "
        "with nothing on disk behind it"
    )


def test_names_with_spaces_or_non_ascii_letters_are_counted(repo):
    write(repo, "platform/scoring/two words.py", "a = 1\n")
    write(repo, "platform/scoring/caf\u00e9.py", "a = 1\nb = 2\n")
    git(repo, "add", ".")

    assert measured(repo)["core_loc"] == 3


def test_a_symlink_is_not_counted_as_what_it_points_at(repo):
    write(repo, "platform/scoring/real.py", "a = 1\nb = 2\n")
    write(repo, "platform/ingest/elastic.py", "c = 3\n")
    (repo / "platform/scoring/alias.py").symlink_to("real.py")
    (repo / "platform/scoring/gone.py").symlink_to("nowhere.py")
    (repo / "platform/scoring/ingest").symlink_to("../ingest")
    git(repo, "add", ".")

    assert measured(repo)["core_loc"] == 3, (
        "a tracked symlink holds a path, not code: counting its target counts "
        "that file twice, and a dangling one or one to a directory crashed"
    )
