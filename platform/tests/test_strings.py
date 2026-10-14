import pathlib
import re

import pytest
import yaml
from django.test import Client

import traffic
from console import strings

pytestmark = pytest.mark.django_db

CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"
TEMPLATES = sorted(path.name for path in CONSOLE.glob("*.html") if path.name != "strings.html")
PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/"]

def tables():
    shown, withheld = strings.shown(), strings.withheld()
    return {language: shown[language] | withheld[language] for language in strings.LANGUAGES}

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

def test_the_blue_page_ships_no_withheld_answer_or_pass_line(client):
    page = client.get("/blue/1/").content.decode()
    rendered = strings.parsed(page[page.index("const STRINGS"):])
    withheld = strings.withheld()

    assert all(withheld[language] for language in strings.LANGUAGES)
    for language in strings.LANGUAGES:
        assert not set(withheld[language]) & set(rendered[language])
        assert not set(withheld[language].values()) & set(rendered[language].values())
        assert not [key for key in withheld[language] if key in page]
    assert "{% comment %}" not in page and "const WITHHELD" not in page

def test_every_foundation_step_has_a_withheld_answer_and_line_in_both_languages():
    import wargames

    withheld = strings.withheld()
    missing = [
        f"{taught['text']}.{part}.{step['id']}"
        for wargame_id in wargames.WARGAMES for taught in wargames.foundations(wargame_id)
        for step in taught.get("steps", []) for part in ("answer", "line")
        if any(f"{taught['text']}.{part}.{step['id']}" not in withheld[language] for language in strings.LANGUAGES)
    ]
    leftover = [key for key in tables()["en"] if re.fullmatch(r"lesson\.[a-z]+\.(?:answer|line)\.[a-z_]+", key)
                and key not in withheld["en"]]

    assert missing == [] and leftover == []

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
    detections = [DetectionRecord("d1", at, "5.188.10.2", None)]

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

@pytest.mark.parametrize("language", ["en", "ko"])
def test_the_benign_warning_names_the_red_console_controls_that_run_benign_cases(language):
    table = tables()[language]
    advice = table["score.warning.no_benign"]

    assert table["red.baseline.run_all"] in advice and table["red.cases.benign"] in advice, (
        "the warning that no benign case was run sends the operator to the red "
        "console, and does not name the controls there by the labels they carry"
    )

ZERO_SUM_KO = "\uc81c\ub85c\uc12c"
SCOREBOARD_LABELS = re.compile(rf"\b(?:TP|FP|FN|TN)\b|(?i:zero-sum|{ZERO_SUM_KO})")

@pytest.mark.parametrize("language", ["en", "ko"])
def test_no_text_a_person_reads_names_the_confusion_matrix_or_a_zero_sum_balance(language):
    offenders = {
        key: text for key, text in tables()[language].items() if SCOREBOARD_LABELS.search(text)
    }

    assert offenders == {}, (
        "the console tells a person what happened in plain words; TP/FP/FN/TN stay in the "
        f"API for agents: {offenders}"
    )

def test_the_console_templates_write_no_confusion_matrix_label_either():
    offenders = [
        name for name in TEMPLATES
        if re.search(r"['\"`>](?:TP|FP|FN|TN)['\"`<]", (CONSOLE / name).read_text())
    ]

    assert offenders == [], offenders

TRUE_POSITIVE_KO = "\uc815\ud0d0"
FALSE_NEGATIVE_KO = "\ubbf8\ud0d0"
FALSE_POSITIVE_KO = "\uc624\ud0d0"
DETECTED_KO = "\ud0d0\uc9c0\ub428"

def test_korean_names_the_confusion_matrix_nowhere_and_says_false_positive_only_as_the_crs_term():
    korean = tables()["ko"]
    labels = {key: text for key, text in korean.items() if re.search(f"{TRUE_POSITIVE_KO}|{FALSE_NEGATIVE_KO}", text)}
    outside_crs = {key: text for key, text in korean.items()
                   if FALSE_POSITIVE_KO in text and not key.startswith("lesson.")}

    assert labels == {}, f"R1: the Korean TP and FN labels (docs/vocabulary.md) label no score: {labels}"
    assert outside_crs == {}, (
        f"the Korean for false positive is the CRS documentation's term, used only in the lesson: {outside_crs}"
    )

def test_the_score_labels_are_states_a_korean_reader_cannot_read_as_noise():
    korean = tables()["ko"]

    assert korean["score.caught"] == DETECTED_KO, "the Korean word for caught also reads as noise"
    assert all("(" not in korean[key] for key in ("score.caught", "score.missed", "score.wrongly_blocked", "score.passed"))

def test_every_customer_action_a_wargame_declares_has_a_label():
    root = pathlib.Path(__file__).resolve().parents[2] / "wargames"
    declared = {action for path in root.glob("*/traffic.yaml")
                for profile in traffic.checked(yaml.safe_load(path.read_text(encoding="utf-8")), path)["profiles"].values()
                for action in profile}
    table = tables()

    for language in strings.LANGUAGES:
        unlabelled = sorted(action for action in declared if f"traffic.action.{action}" not in table[language])
        assert not unlabelled, f"the debrief shows these customer actions by their ids in {language}: {unlabelled}"
