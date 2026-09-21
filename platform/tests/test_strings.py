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
    unknown = sorted(used_keys() - set(table["en"]))

    assert not unknown, (
        f"the console renders these keys and the table has no text for them, so the "
        f"raw key appears on screen: {unknown}"
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
