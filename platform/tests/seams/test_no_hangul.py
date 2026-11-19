import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
SCANNED = (".py", ".ts", ".tsx", ".html", ".json", ".yaml", ".yml", ".md", ".sh", ".conf")
SKIPPED = {".git", ".venv", "node_modules", "__pycache__", ".claude", ".ruff_cache"}
ALLOWED_FILES = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/vocabulary.md",
    "strings/console.json",
    "strings/server.json",
    "wargames/board/app/posts/management/commands/seed.py",
)
ALLOWED_FOLDERS = ("wargames/board/app/posts/templates/",)
KOREAN_TEST_INPUTS: tuple[str, ...] = ()
REWRITTEN_AT_THE_DOCS_STEP = (
    "docs/DECISIONS.md",
    "docs/OPENSTACK.md",
    "docs/STATE.md",
    "docs/TROUBLESHOOTING.md",
    "docs/state/now.md",
)


def scanned() -> list[str]:
    found = []
    for folder, folders, files in os.walk(REPO):
        folders[:] = [name for name in folders if name not in SKIPPED]
        found += [str((Path(folder) / name).relative_to(REPO)) for name in files if name.endswith(SCANNED)]
    return sorted(found)


def allowed(path: str) -> bool:
    return (path in ALLOWED_FILES or path in KOREAN_TEST_INPUTS or path in REWRITTEN_AT_THE_DOCS_STEP
            or path.startswith(ALLOWED_FOLDERS))


def carries_hangul(path: str) -> bool:
    return bool(HANGUL.search((REPO / path).read_text(encoding="utf-8", errors="replace")))


def test_hangul_appears_only_in_the_named_korean_places():
    strays = [path for path in scanned() if not allowed(path) and carries_hangul(path)]

    assert strays == [], f"Korean belongs in strings/*.json and the named places only: {strays}"


def test_every_named_korean_place_exists():
    named = (*ALLOWED_FILES, *KOREAN_TEST_INPUTS, *REWRITTEN_AT_THE_DOCS_STEP)

    assert [path for path in named if not (REPO / path).is_file()] == []
    assert [folder for folder in ALLOWED_FOLDERS if not (REPO / folder).is_dir()] == []


def test_the_docs_waiting_for_their_rewrite_still_carry_hangul():
    cleaned = [path for path in REWRITTEN_AT_THE_DOCS_STEP if not carries_hangul(path)]

    assert cleaned == [], f"remove these from REWRITTEN_AT_THE_DOCS_STEP: {cleaned}"


def test_the_scan_sees_hangul_in_a_string_table():
    assert carries_hangul("strings/console.json")
    assert "platform/content/service.py" in scanned()
