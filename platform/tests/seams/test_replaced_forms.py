import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "docs/DECISIONS.md"
REPLACES = re.compile(r"^Replaces: `(?P<pattern>[^`]+)`(?: in (?P<within>(?:`[^`]+`(?:, )?)+))?"
                      r"(?: except (?P<outside>(?:`[^`]+`(?:, )?)+))?\s*$")
QUOTED = re.compile(r"`([^`]+)`")
HISTORY = (
    "docs/DECISIONS.md", "docs/research/", "docs/specs/",
    "uv.lock", "front/package-lock.json", "openapi/schema.yaml",
)
GENERATED = re.compile(r"/migrations/|\.binlog$|^wargames/[^/]+/probes/|\.(?:png|jpg|jpeg|gif|ico|woff2?|mmdb|pcap|gz)$")


@dataclass(frozen=True)
class Replaced:
    heading: str
    pattern: re.Pattern
    within: tuple[str, ...]
    outside: tuple[str, ...]

    def covers(self, path: str) -> bool:
        if self.within and not path.startswith(self.within):
            return False
        return not path.startswith(self.outside) if self.outside else True


def replaced_forms(text: str) -> list[Replaced]:
    heading, found = "", []
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:]
        matched = REPLACES.match(line)
        if matched:
            found.append(Replaced(
                heading, re.compile(matched["pattern"]),
                tuple(QUOTED.findall(matched["within"] or "")),
                tuple(QUOTED.findall(matched["outside"] or "")),
            ))
    return found


def scanned_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    paths = [entry.decode() for entry in listed.split(b"\0") if entry]
    return [path for path in paths
            if not path.startswith(HISTORY) and not GENERATED.search(path) and (REPO / path).is_file()]


def lines_of(path: str) -> list[str]:
    raw = (REPO / path).read_bytes()
    if b"\0" in raw:
        return []
    return raw.decode("utf-8", errors="replace").splitlines()


def still_written(forms: list[Replaced], paths: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in paths:
        reaching = [form for form in forms if form.covers(path)]
        if not reaching:
            continue
        for number, line in enumerate(lines_of(path), 1):
            for form in reaching:
                if form.pattern.search(line):
                    found.setdefault(form.pattern.pattern, []).append(f"{path}:{number}: {line.strip()[:120]}")
    return found


def test_a_replaces_line_names_a_pattern_and_optional_paths():
    forms = replaced_forms(
        "## 2026-11-28 — One\nReplaces: `old_name`\n"
        "## 2026-11-29 — Two\nReplaces: `옛말` in `docs/`, `README.md` except `docs/OPENSTACK.md`\n"
    )

    assert [(form.heading, form.pattern.pattern, form.within, form.outside) for form in forms] == [
        ("2026-11-28 — One", "old_name", (), ()),
        ("2026-11-29 — Two", "옛말", ("docs/", "README.md"), ("docs/OPENSTACK.md",)),
    ]


def test_a_form_reaches_only_its_paths():
    form = replaced_forms("Replaces: `x` in `docs/` except `docs/old.md`\n")[0]

    assert [form.covers(path) for path in ("docs/a.md", "docs/old.md", "README.md")] == [True, False, False]


def test_history_and_generated_files_are_not_scanned():
    paths = scanned_files()

    assert "README.md" in paths and "docs/ARCHITECTURE.md" in paths
    assert not [path for path in paths if path.startswith(HISTORY) or GENERATED.search(path)]


def test_every_decisions_replaces_line_compiles():
    assert FORMS, "docs/DECISIONS.md names no Replaces line"


FORMS = replaced_forms(DECISIONS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("form", FORMS, ids=[f"replaces-{number}" for number in range(1, len(FORMS) + 1)])
def test_no_replaced_form_is_still_written(form):
    found = still_written([form], scanned_files()).get(form.pattern.pattern, [])

    assert not found, (
        f"docs/DECISIONS.md '{form.heading}' replaced `{form.pattern.pattern}`, "
        f"and {len(found)} lines still write it:\n" + "\n".join(found)
    )
