import importlib.util
import json
import re
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "services:\n  web:\n    image: nginx:1.27\n"


def load_measure():
    loader = SourceFileLoader("measure", str(ROOT / "bin/measure"))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("measure", loader)
    )
    loader.exec_module(module)
    return module


@pytest.fixture
def measure(tmp_path, monkeypatch):
    module = load_measure()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


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


def test_only_tests_pytest_would_collect_are_counted(repo):
    write(
        repo, "platform/tests/test_collected.py",
        'def test_one():\n    pass\n\n\nSOURCE = """\ndef test_in_a_string():\n'
        '    pass\n"""\n',
    )
    write(repo, "platform/tests/deeper/test_nested.py", "def test_two():\n    pass\n")
    write(repo, "platform/tests/helpers.py", "def test_never_collected():\n    pass\n")
    write(repo, "test/conftest.py", "def test_nor_this():\n    pass\n")
    git(repo, "add", ".")

    assert measured(repo)["tests"] == 2, (
        "a def test_ in a file pytest never collects, or inside a string, runs "
        "nothing, and counting it lets a real test go without the floor noticing"
    )


def test_two_tests_with_one_name_in_a_module_are_refused(repo):
    write(
        repo, "test/test_twice.py",
        "def test_same():\n    assert False\n\n\ndef test_same():\n    pass\n",
    )
    git(repo, "add", ".")

    done = run_measure(repo)

    assert done.returncode != 0, (
        f"the second test_same replaces the first, so pytest runs one test "
        f"and the floor counted two:\n{done.stdout}"
    )
    assert "test/test_twice.py" in done.stderr, done.stderr
    assert "test_same" in done.stderr, done.stderr


COMPOSE_SHAPES = {
    "this repo": (ROOT / "compose.yaml").read_text(),
    "indented by four": (
        "services:\n    web:\n        image: a:1\n    db:\n        image: b:1\n"
    ),
    "anchored and aliased": (
        "services:\n  web: &web\n    image: a:1\n  worker: *web\n"
    ),
    "flow values": (
        'services:\n  web: {image: "a:1"}\n  db: {image: "b:1"}\n'
    ),
    "quoted and commented": (
        "services:   # the stack\n"
        '  "web":   # the target\n'
        "    image: a:1\n"
        "  'db':\n"
        "    image: b:1\n"
    ),
    "anchored mapping with merged bodies": (
        "x-base: &base\n  image: a:1\n"
        "services: &all\n  web:\n    <<: *base\n  db:\n    <<: *base\n"
    ),
}


@pytest.mark.parametrize(
    "text", COMPOSE_SHAPES.values(), ids=list(COMPOSE_SHAPES)
)
def test_services_are_counted_as_yaml_reads_them(measure, tmp_path, text):
    (tmp_path / "compose.yaml").write_text(text)

    assert measure.services() == len(yaml.safe_load(text)["services"]), (
        "a service measure cannot see is a service the gate lets in for free"
    )


def test_services_are_read_from_the_file_compose_would_pick(measure, tmp_path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE)

    assert measure.services() == 1


@pytest.mark.parametrize(
    "name",
    [
        "compose.override.yml",
        "compose.override.yaml",
        "docker-compose.override.yml",
        "docker-compose.override.yaml",
    ],
)
def test_an_override_file_is_refused_by_name(measure, tmp_path, name):
    (tmp_path / "compose.yaml").write_text(COMPOSE)
    (tmp_path / name).write_text("services:\n  hidden:\n    image: a:1\n")

    with pytest.raises(SystemExit, match=re.escape(name)):
        measure.services()


UNCOUNTABLE = {
    "include": (
        "include:\n  - more.yaml\nservices:\n  web:\n    image: a:1\n",
        "line 1: include",
    ),
    "services merged in": (
        "x-more: &more\n  db:\n    image: b:1\n"
        "services:\n  <<: *more\n  web:\n    image: a:1\n",
        "line 5: <<",
    ),
    "flow mapping": (
        'services: {web: {image: "a:1"}, db: {image: "b:1"}}\n',
        "line 1: services",
    ),
    "aliased mapping": (
        "x-all: &all\n  web:\n    image: a:1\nservices: *all\n",
        "line 4: services",
    ),
    "tab indent": (
        "services:\n\tweb:\n\t\timage: a:1\n",
        "line 2",
    ),
}


@pytest.mark.parametrize(
    "text, named", UNCOUNTABLE.values(), ids=list(UNCOUNTABLE)
)
def test_services_measure_cannot_count_are_refused_not_skipped(
    measure, tmp_path, text, named
):
    (tmp_path / "compose.yaml").write_text(text)

    with pytest.raises(SystemExit, match=re.escape(named)):
        measure.services()
