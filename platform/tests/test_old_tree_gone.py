import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = "platform/tests/test_old_tree_gone.py"
OLD_API = re.compile(r"(?<![\w./])api\.\w|^\s*(from|import) api\b", re.MULTILINE)
SCENARIO = re.compile(r"scenario", re.IGNORECASE)

GONE = (
    "platform/accounts", "platform/attack", "platform/content", "platform/defence", "platform/events",
    "platform/ingest", "platform/match", "platform/range", "platform/referee", "platform/rules",
    "platform/lessons", "platform/domain/ledger.py", "platform/domain/checks.py",
    "platform/training/defence/drift.py", "platform/training/round/follow.py",
    "platform/training/management/commands/follow.py",
    "front/src/pages/Lesson.tsx", "front/src/panes/StepCard.tsx", "front/src/ui/Steps.tsx",
    "front/src/panes/staff/StepsEditor.tsx", "bots/client", "bin/gen-clients", "openapi/python-client.yaml",
    "docs/superpowers/plans", "metrics.json", "bin/measure",
)


def tracked():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [name for name in listed.stdout.decode().split("\0") if name]


def is_held_or_prose(name):
    return (name.startswith("docs/") or name.endswith(".md")
            or name == SELF or not (ROOT / name).is_file())


def referencing():
    found = set()
    for name in tracked():
        if is_held_or_prose(name):
            continue
        try:
            text = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        if SCENARIO.search(text) or (not name.startswith("front/") and OLD_API.search(text)):
            found.add(name)
    return found


def test_the_old_product_tree_is_gone():
    assert [path for path in GONE if (ROOT / path).exists()] == []


def test_no_file_names_the_old_api_or_scenarios():
    assert referencing() == set(), (
        "a file names api.* or a scenario; remove the reference"
    )
