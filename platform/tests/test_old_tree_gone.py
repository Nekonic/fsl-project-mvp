import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = "platform/tests/test_old_tree_gone.py"
OLD_REFERENCE = re.compile(r"(?<![\w./])api\.\w|^\s*(from|import) api\b|scenario", re.IGNORECASE | re.MULTILINE)

GONE = (
    "platform/api", "platform/console", "platform/wargames.py", "platform/lifecycle.py",
    "platform/game.py", "platform/scenarios.py", "platform/traffic.py", "platform/topology.py",
    "wargames/board/scenario.yaml", "wargames/corp/scenario.yaml", "deploy/openstack/network.yaml",
    "deploy/suricata/rules/no-xss.rules", "deploy/suricata/rules/no-uri-sqli.rules",
    "deploy/suricata/rules/broken-sort.rules", "deploy/suricata/rules/spaced-sort.rules",
    "docs/superpowers/plans", "metrics.json", "bin/measure",
)

PENDING = {
    "redteam/run.py": "moves to platform/attack or test/",
    "platform/vm-terminal.sh": "rewritten on seat-token auth",
    "bin/prune": "re-pointed at the new tables",
}

REFUSES_THE_OLD_KIND = {"platform/tests/domain/test_problems.py"}


def tracked():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [name for name in listed.stdout.decode().split("\0") if name]


def is_held_or_prose(name):
    return (name.startswith(("platform/carry/", "docs/")) or name.endswith(".md")
            or name == SELF or name in REFUSES_THE_OLD_KIND or not (ROOT / name).is_file())


def referencing():
    found = set()
    for name in tracked():
        if is_held_or_prose(name):
            continue
        try:
            text = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        if OLD_REFERENCE.search(text):
            found.add(name)
    return found


def test_the_old_product_tree_is_gone():
    assert [path for path in GONE if (ROOT / path).exists()] == []


def test_only_the_files_still_waiting_for_their_rewrite_name_the_old_api_or_scenarios():
    assert referencing() == set(PENDING), (
        "a file outside platform/carry names api.* or a scenario; either remove the reference "
        "or, once a pending file is rewritten, drop it from PENDING"
    )


def test_every_pending_file_exists():
    assert [name for name in PENDING if not (ROOT / name).is_file()] == []
