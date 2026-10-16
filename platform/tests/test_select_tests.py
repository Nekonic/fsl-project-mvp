import importlib.util
import io
import json
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
    "platform/api/__init__.py": "",
    "platform/api/views.py": "import topology\n\ndef show():\n    return topology.layout()\n",
    "platform/tests/__init__.py": "",
    "platform/tests/test_topology.py": "import topology\n\ndef test_layout():\n    assert topology.layout() == []\n",
    "platform/tests/test_views.py": "from api import views\n\ndef test_show():\n    assert views.show() == []\n",
    "platform/tests/test_scoreboard.py": "import scoreboard\n\ndef test_board():\n    assert scoreboard.board() == {}\n",
    "platform/console/templates/console/blue_topology.html": "<div id=\"map\"></div>\n",
    "platform/tests/test_topology_console.py": (
        "from pathlib import Path\n\nPANE = 'blue_topology.html'\n\n"
        "def test_pane_is_named():\n    assert PANE\n"
    ),
}


def selected(chosen):
    return sorted(path.rsplit("/", 1)[-1] for path in chosen.unit)


def test_a_docs_only_change_selects_no_test(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"README.md": "M", "docs/STATE.md": "M", "metrics.json": "M"})
    said = io.StringIO()
    selector.report(chosen, root, said)

    assert chosen.docs_only and chosen.unit_kind == "none" and chosen.acceptance_kind == "none"
    assert "docs only — no tests" in said.getvalue(), said.getvalue()
    assert selector.plan_lines(chosen) == ["unit none", "acceptance none"]


def test_a_module_change_selects_the_test_files_that_import_it(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"platform/topology.py": "M"})

    assert selected(chosen) == ["test_topology.py", "test_views.py"], (
        "test_topology imports topology and test_views imports api.views, which imports "
        "it; test_scoreboard reaches neither"
    )
    assert chosen.unit_kind == "some"


def test_the_reason_for_a_test_reached_through_another_module_names_the_path(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"platform/topology.py": "M"})

    assert chosen.unit["platform/tests/test_views.py"] == [
        "imports platform/api/views.py > platform/topology.py"
    ]


def test_a_template_change_selects_the_tests_naming_that_template(repo):
    root = repo(SMALL)

    chosen = selector.select(root, {"platform/console/templates/console/blue_topology.html": "M"})

    assert selected(chosen) == ["test_topology_console.py"]
    assert chosen.acceptance_kind == "none", "the console is not range-facing"


def test_a_template_rendered_for_a_requested_page_selects_the_test_requesting_it(repo):
    root = repo({
        **SMALL,
        "platform/fsl/__init__.py": "",
        "platform/fsl/urls.py": (
            "from django.urls import path\n\nfrom api import views\nfrom console import views as console\n\n"
            "urlpatterns = [\n    path(\"api/show/\", views.show),\n"
            "    path(\"blue/<int:session_id>/\", console.blue),\n]\n"
        ),
        "platform/console/__init__.py": "",
        "platform/console/views.py": "def blue(request, session_id):\n    return 'console/blue.html'\n",
        "platform/console/templates/console/blue.html": "{% include \"console/blue_topology.html\" %}\n",
        "platform/tests/test_blue_page.py": (
            "def test_blue(client):\n    assert client.get(f\"/blue/{1}/\")\n"
        ),
        "platform/tests/test_show_api.py": (
            "def test_show(client):\n    assert client.get(\"/api/show/?all=1\")\n"
        ),
    })

    chosen = selector.select(root, {"platform/console/templates/console/blue_topology.html": "M"})

    assert "test_blue_page.py" in selected(chosen)
    assert "test_show_api.py" not in selected(chosen), (
        "the API test requests a view that renders no template"
    )


def test_reading_a_python_file_as_text_does_not_pull_in_what_it_imports(repo):
    root = repo({
        **SMALL,
        "platform/tests/test_seams.py": (
            "from pathlib import Path\n\ndef test_views_is_short():\n"
            "    assert Path('api/views.py').read_text()\n"
        ),
    })

    reaches_views = selector.select(root, {"platform/api/views.py": "M"})
    reaches_topology = selector.select(root, {"platform/topology.py": "M"})

    assert "test_seams.py" in selected(reaches_views)
    assert "test_seams.py" not in selected(reaches_topology)


def test_a_file_no_test_reaches_falls_back_to_the_whole_unit_suite(repo):
    root = repo({**SMALL, "deploy/nginx/extra.conf": "server {}\n"})

    chosen = selector.select(root, {"deploy/nginx/extra.conf": "M"})
    said = io.StringIO()
    selector.report(chosen, root, said)

    assert chosen.unit_kind == "full" and chosen.unmapped == ["deploy/nginx/extra.conf"]
    assert "no test reaches it" in said.getvalue()
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


def test_a_docs_only_change_still_runs_the_ratchet(repo, tmp_path):
    root = repo({
        **SMALL,
        "compose.yaml": "services:\n  web:\n    image: nginx:1.27\n",
        "metrics.json": json.dumps({
            "core_loc": 0, "product_loc": 0, "dependencies": 0,
            "services": 1, "wargame_services": 0, "tests": 99,
        }) + "\n",
    })
    for script in ("verify", "measure", "select-tests"):
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
    assert "the test suite got smaller" in done.stdout and done.returncode == 1, (
        f"a docs-only change skipped the tests but must not skip the ratchet:\n{done.stdout}"
    )
