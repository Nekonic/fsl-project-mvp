import json
import pathlib
import re

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"
TEMPLATES = ["base.html", "main.html", "session.html", "red.html", "blue.html"]
PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/"]

def tables():
    source = (CONSOLE / "strings.html").read_text()
    found = {}
    for language in ("en", "ko"):
        start = source.index(f"    {language}: {{")
        block = source[start + source[start:].index("{"):]
        depth, end = 0, 0
        for position, character in enumerate(block):
            depth += (character == "{") - (character == "}")
            if depth == 0:
                end = position + 1
                break
        found[language] = json.loads(re.sub(r",(\s*})", r"\1", block[:end]))
    return found

def used_keys():
    keys = set()
    for name in TEMPLATES:
        source = (CONSOLE / name).read_text()
        keys |= set(re.findall(r'data-t(?:-placeholder|-title)?="([^"]+)"', source))
        keys |= set(re.findall(r'(?<![A-Za-z0-9_])t\(\s*"([^"]+)"', source))
    return keys

def test_the_two_languages_carry_exactly_the_same_keys():
    table = tables()
    missing_ko = sorted(set(table["en"]) - set(table["ko"]))
    missing_en = sorted(set(table["ko"]) - set(table["en"]))

    assert not missing_ko, f"no Korean for: {missing_ko}"
    assert not missing_en, f"Korean-only keys with no English: {missing_en}"

def test_every_key_the_console_asks_for_exists():
    table = tables()
    asked, families = set(), set()
    for key in used_keys():
        (families if key.endswith(".") else asked).add(key)

    unknown = sorted(asked - set(table["en"]))
    assert not unknown, (
        f"the console renders these keys and the table has no text for them, so the "
        f"raw key appears on screen: {unknown}"
    )

    empty = sorted(
        family for family in families
        if not any(key.startswith(family) for key in table["en"])
    )
    assert not empty, (
        f"the console builds keys under {empty} out of data, and the table has "
        f"nothing under them at all, so every one of them renders as its own id"
    )

def test_no_string_in_the_table_is_left_untranslated():
    table = tables()
    same = sorted(
        key for key, text in table["en"].items()
        if table["ko"].get(key) == text and not re.fullmatch(r"[\W\d]+|[A-Z]{2,4}", text)
    )
    allowed = {"common.brand"}

    assert not set(same) - allowed, (
        f"these are identical in both tables, which means the Korean was never written: "
        f"{sorted(set(same) - allowed)}"
    )

def test_a_string_with_placeholders_is_called_with_arguments():
    english = tables()["en"]
    offenders = []

    for name in TEMPLATES:
        source = (CONSOLE / name).read_text()
        for match in re.finditer(r'(?<![A-Za-z0-9_])t\(\s*"([^"]+)"([^)]*)', source):
            key, rest = match.group(1), match.group(2)
            wanted = len(set(re.findall(r"\{(\d+)\}", english.get(key, ""))))
            given = 0 if not rest.strip() else rest.count(",") + 1
            if wanted and given < wanted:
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{name}:{line} t({key!r}) needs {wanted}, got {given}")

    assert not offenders, (
        "these render a literal {0} on screen because the caller passed no value:\n"
        + "\n".join(offenders)
    )

def test_a_placeholder_in_one_language_exists_in_the_other():
    table = tables()
    mismatched = []
    for key, english in table["en"].items():
        wanted = set(re.findall(r"\{(\d+)\}", english))
        got = set(re.findall(r"\{(\d+)\}", table["ko"].get(key, "")))
        if wanted != got:
            mismatched.append(f"{key}: en{sorted(wanted)} ko{sorted(got)}")

    assert not mismatched, (
        f"a value is interpolated into one language and dropped in the other: {mismatched}"
    )

@pytest.fixture
def client():
    return Client()

@pytest.mark.parametrize("path", PAGES)
def test_every_page_ships_the_string_table(client, path):
    page = client.get(path).content.decode()

    assert "const STRINGS" in page, path
    assert 'id="language"' in page, path

def test_no_korean_is_written_outside_the_string_table():
    korean = re.compile(r"[\uac00-\ud7a3]")
    offenders = [
        name for name in TEMPLATES if korean.search((CONSOLE / name).read_text())
    ]

    assert not offenders, (
        f"CLAUDE.md confines Korean to the string table; these carry it inline: {offenders}"
    )

def test_nothing_the_platform_sends_to_the_page_is_prose():
    from datetime import datetime, timezone

    from scoring.correlate import correlate
    from scoring.metrics import score
    from scoring.types import CaseRecord, DetectionRecord

    at = datetime(2026, 9, 25, tzinfo=timezone.utc)
    cases = [
        CaseRecord("a1", "sqli", True, "marker", None, at, at),
        CaseRecord("a2", "scan", True, "window", None, at, at),
    ]
    detections = [DetectionRecord("d1", "suricata", "x", at, "5.188.10.2", None)]

    keys = [warning[0] for warning in score(correlate(cases, detections)).warnings]
    english = tables()["en"]

    assert {
        "score.warning.no_marker", "score.warning.no_source_ip", "score.warning.no_benign",
    } <= set(keys), keys
    unknown = [
        key for key in keys
        if not re.fullmatch(r"score\.warning\.[a-z_]+", key) or key not in english
    ]
    assert not unknown, (
        f"the console looks every score warning up in the string table and these "
        f"are not in it, so they reach the screen as written whatever language "
        f"the page is in: {unknown}"
    )
