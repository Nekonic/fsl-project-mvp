import importlib.util
import os
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_selector():
    loader = SourceFileLoader("select_tests", str(ROOT / "bin/select-tests"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("select_tests", loader))
    sys.modules["select_tests"] = module
    loader.exec_module(module)
    return module


selector = load_selector()


def git(root, *argv):
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *argv],
        cwd=root, check=True, capture_output=True,
    ).stdout


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")

    def build(files):
        write(root, files)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "start")
        return root

    return build


SMALL = {
    "README.md": "# range\n",
    "docs/STATE.md": "state\n",
    "platform/topology.py": "def layout():\n    return []\n",
    "platform/scoreboard.py": "def board():\n    return {}\n",
    "platform/match/__init__.py": "",
    "platform/match/views.py": "import topology\n\ndef show():\n    return topology.layout()\n",
    "platform/tests/__init__.py": "",
    "platform/tests/test_topology.py": "import topology\n\ndef test_layout():\n    assert topology.layout() == []\n",
    "platform/tests/test_views.py": "from match import views\n\ndef test_show():\n    assert views.show() == []\n",
    "platform/tests/test_scoreboard.py": "import scoreboard\n\ndef test_board():\n    assert scoreboard.board() == {}\n",
    "front/src/panes/Score.tsx": "export function Score() { return null }\n",
    "platform/tests/test_score_pane.py": (
        "from pathlib import Path\n\nPANE = 'Score.tsx'\n\n"
        "def test_pane_is_named():\n    assert PANE\n"
    ),
}


def selected(chosen):
    return sorted(path.rsplit("/", 1)[-1] for path in chosen.unit)


def test_a_docs_only_change_selects_no_test(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"README.md": "M", "docs/STATE.md": "M"})

    assert chosen.docs_only
    assert selector.plan_lines(chosen) == ["unit none", "acceptance none"]


def test_a_module_change_selects_the_test_files_that_import_it(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"platform/topology.py": "M"})

    assert selected(chosen) == ["test_topology.py", "test_views.py"], (
        "test_topology imports topology and test_views imports match.views, which imports "
        "it; test_scoreboard reaches neither"
    )
    assert chosen.unit_kind == "some"


def test_a_front_change_selects_the_tests_naming_that_file(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"front/src/panes/Score.tsx": "M"})

    assert selected(chosen) == ["test_score_pane.py"]
    assert chosen.acceptance_kind == "none", "the front end is not range-facing"


def test_a_data_file_a_requested_view_reads_selects_the_test_requesting_it(repo):
    root = repo({
        **SMALL,
        "platform/cr/__init__.py": "",
        "platform/cr/urls.py": (
            "from django.urls import path\n\nfrom match import views\nfrom training.content import views as content\n\n"
            "urlpatterns = [\n    path(\"api/show/\", views.show),\n"
            "    path(\"api/wargames/<str:name>/\", content.wargame),\n]\n"
        ),
        "platform/training/__init__.py": "",
        "platform/training/content/__init__.py": "",
        "platform/training/content/views.py": (
            "from pathlib import Path\n\n\ndef wargame(request, name):\n"
            "    return (Path('wargames') / name / 'wargame.yaml').read_text()\n"
        ),
        "wargames/board/wargame.yaml": "name: board\n",
        "platform/tests/test_wargame_api.py": (
            "def test_wargame(client):\n    assert client.get(f\"/api/wargames/{'board'}/\")\n"
        ),
        "platform/tests/test_show_api.py": (
            "def test_show(client):\n    assert client.get(\"/api/show/?all=1\")\n"
        ),
    })

    chosen = selector.select(root, {"wargames/board/wargame.yaml": "M"})

    assert "test_wargame_api.py" in selected(chosen)
    assert "test_show_api.py" not in selected(chosen), (
        "the API test requests a view that reads no wargame file"
    )


def test_reading_a_python_file_as_text_does_not_pull_in_what_it_imports(repo):
    root = repo({
        **SMALL,
        "platform/tests/test_seams.py": (
            "from pathlib import Path\n\ndef test_views_is_short():\n"
            "    assert Path('match/views.py').read_text()\n"
        ),
    })

    reaches_views = selector.select(root, {"platform/match/views.py": "M"})
    reaches_topology = selector.select(root, {"platform/topology.py": "M"})

    assert "test_seams.py" in selected(reaches_views)
    assert "test_seams.py" not in selected(reaches_topology)


def test_a_file_no_test_reaches_falls_back_to_the_whole_unit_suite(repo):
    root = repo({**SMALL, "deploy/nginx/extra.conf": "server {}\n"})

    chosen = selector.select(root, {"deploy/nginx/extra.conf": "M"})

    assert chosen.unmapped == ["deploy/nginx/extra.conf"]
    assert selector.plan_lines(chosen)[0] == "unit full"


def test_the_unit_conftest_runs_the_whole_unit_suite(repo):
    root = repo({**SMALL, "platform/tests/conftest.py": "import pytest\n"})

    chosen = selector.select(root, {"platform/tests/conftest.py": "M"})

    assert chosen.unit_kind == "full"


def test_a_deleted_module_selects_the_tests_still_importing_it(repo):
    root = repo(SMALL)
    (root / "platform/scoreboard.py").unlink()
    git(root, "add", "-A")

    chosen = selector.select(root, {"platform/scoreboard.py": "D"})

    assert selected(chosen) == ["test_scoreboard.py"]


def test_a_range_facing_change_no_acceptance_test_names_needs_all_acceptance(repo):
    root = repo({**SMALL, "test/test_board.py": "def test_board():\n    pass\n"})

    chosen = selector.select(root, {"platform/topology.py": "M"})

    assert chosen.acceptance_kind == "full" and chosen.acceptance_whole == ["platform/topology.py"]


def test_an_acceptance_test_is_chosen_by_the_file_it_names(repo):
    root = repo({
        **SMALL,
        "deploy/suricata/rules/local.rules": "alert http any any -> any any (sid:1;)\n",
        "test/conftest.py": "import pytest\n",
        "test/test_rules.py": "RULES = 'deploy/suricata/rules/local.rules'\n\ndef test_rules():\n    pass\n",
        "test/test_board.py": "def test_board():\n    pass\n",
        "platform/tests/test_rule_file.py": "def test_rules():\n    assert 'local.rules'\n",
    })

    chosen = selector.select(root, {"deploy/suricata/rules/local.rules": "M"})

    assert chosen.acceptance_kind == "some"
    assert sorted(chosen.acceptance) == ["test/test_rules.py"]
    assert selector.plan_lines(chosen) == [
        "unit some", "unit-file tests/test_rule_file.py",
        "acceptance some", "acceptance-module test_rules",
    ]


def test_the_acceptance_conftest_reaches_every_acceptance_test(repo):
    root = repo({
        **SMALL,
        "test/conftest.py": "pytest_plugins = [\"shared_sessions\"]\n",
        "test/shared_sessions.py": "import pytest\n",
        "test/test_a.py": "def test_a():\n    pass\n",
        "test/test_b.py": "def test_b():\n    pass\n",
    })

    chosen = selector.select(root, {"test/shared_sessions.py": "M"})

    assert sorted(chosen.acceptance) == ["test/test_a.py", "test/test_b.py"]


def test_the_changed_files_are_the_commits_since_the_base_and_the_uncommitted_ones(repo):
    root = repo(SMALL)
    base = git(root, "rev-parse", "HEAD").decode().strip()
    write(root, {"platform/topology.py": "def layout():\n    return [1]\n"})
    git(root, "commit", "-qam", "change")
    write(root, {"platform/scoreboard.py": "def board():\n    return {1: 1}\n", "platform/new.py": ""})

    since = selector.changed_files(root, base)
    committed = selector.changed_files(root, f"{base}..HEAD")

    assert since == {"platform/new.py": "A", "platform/scoreboard.py": "M", "platform/topology.py": "M"}
    assert committed == {"platform/topology.py": "M"}


def test_a_docs_only_change_runs_no_test_and_passes(repo):
    root = repo(SMALL)
    for script in ("verify", "select-tests"):
        (root / "bin").mkdir(exist_ok=True)
        shutil.copy(ROOT / "bin" / script, root / "bin" / script)
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)
    write(root, {".gitignore": ".venv\n"})
    git(root, "add", "-A")
    git(root, "commit", "-qm", "tools")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    write(root, {"README.md": "# range, documented\n"})

    done = subprocess.run(
        [str(root / "bin/verify"), "--changed", base],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"},
    )

    assert "docs only — no tests" in done.stdout, done.stdout + done.stderr
    assert done.returncode == 0, done.stdout + done.stderr
