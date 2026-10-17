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

def foundation_steps():
    import wargames

    for wargame_id in wargames.WARGAMES:
        for taught in wargames.foundations(wargame_id):
            steps = taught.get("steps", [])
            for at, step in enumerate(steps):
                yield taught, step, at == len(steps) - 1

def test_every_foundation_step_has_its_text_and_a_withheld_pass_line_in_both_languages():
    shown, withheld = strings.shown(), strings.withheld()
    missing = []
    for taught, step, solo in foundation_steps():
        asks = step["check"]["kind"] in ("answer", "choice")
        parts = ["title", "coach"] + (["label"] if asks else []) + ([] if solo else ["nudge", "hint"])
        for language in strings.LANGUAGES:
            missing += [f"{language} {taught['text']}.{part}.{step['id']}" for part in parts
                        if f"{taught['text']}.{part}.{step['id']}" not in shown[language]]
            if f"{taught['text']}.ok.{step['id']}" not in withheld[language]:
                missing.append(f"{language} withheld {taught['text']}.ok.{step['id']}")

    assert missing == [], f"a foundation step would show its raw key or no pass line: {missing}"

def test_a_foundation_ends_on_a_solo_step_with_no_help_written_for_it():
    table = tables()["en"]
    helped = [f"{taught['text']}.{part}.{step['id']}" for taught, step, solo in foundation_steps() if solo
              for part in ("nudge", "hint", "callout") if f"{taught['text']}.{part}.{step['id']}" in table]

    assert helped == [], f"the last step of a lesson is done without help, yet these are written: {helped}"

def test_foundations_carry_no_answer_rung_and_pass_lines_never_ship_in_the_page():
    import wargames

    texts = {taught["text"] for wargame_id in wargames.WARGAMES for taught in wargames.foundations(wargame_id)}
    shown = strings.shown()["en"]
    leftover = [key for key in tables()["en"]
                if ".".join(key.split(".")[:2]) in texts and re.match(r"lesson\.[a-z]+\.(?:answer|line)\.", key)]
    shipped = [key for key in shown if re.match(r"lesson\.[a-z]+\.ok\.", key)]

    assert leftover == [] and shipped == [], (leftover, shipped)

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


def test_every_customer_action_a_wargame_declares_has_a_label():
    root = pathlib.Path(__file__).resolve().parents[2] / "wargames"
    declared = {action for path in root.glob("*/traffic.yaml")
                for profile in traffic.checked(yaml.safe_load(path.read_text(encoding="utf-8")), path)["profiles"].values()
                for action in profile}
    table = tables()

    for language in strings.LANGUAGES:
        unlabelled = sorted(action for action in declared if f"traffic.action.{action}" not in table[language])
        assert not unlabelled, f"the debrief shows these customer actions by their ids in {language}: {unlabelled}"

def test_every_pane_a_step_opens_has_an_open_button_label_in_both_languages():
    import wargames

    opened = {step["point"]["opens"] for wargame_id in wargames.WARGAMES
              for unit in wargames.foundations(wargame_id) + wargames.scenarios(wargame_id)
              for step in unit.get("steps", []) if isinstance(step.get("point"), dict) and step["point"].get("opens")}
    table = tables()
    unlabelled = sorted(f"{language} lesson.open.{pane}" for pane in opened for language in strings.LANGUAGES
                        if f"lesson.open.{pane}" not in table[language])

    assert opened and unlabelled == [], f"a step card offers to open these panes with no label: {unlabelled}"

def test_no_pass_line_names_an_option_a_later_step_of_its_lesson_offers():
    import wargames

    withheld, table = strings.withheld(), tables()
    named = []
    for wargame_id in wargames.WARGAMES:
        for taught in wargames.foundations(wargame_id):
            steps = taught.get("steps", [])
            for at, step in enumerate(steps):
                later = {option for after in steps[at + 1:] for option in after["check"].get("options", [])}
                for language in strings.LANGUAGES:
                    words = set(re.findall(r"[\w-]+", withheld[language].get(f"{taught['text']}.ok.{step['id']}", "")))
                    named += [f"{language} {taught['text']}.ok.{step['id']}: {option}" for option in later
                              if table[language].get(f"lesson.choice.{option}") in words]

    assert named == [], f"a pass line stays on screen while a later step asks, and gives its answer away: {named}"
