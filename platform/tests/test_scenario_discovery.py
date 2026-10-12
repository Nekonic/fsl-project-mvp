import re

import pytest
import yaml

import wargames

A_SCENARIO = {
    "name": "Demo",
    "description": "A scenario discovered from disk.",
    "image": "ghcr.io/nekonic/fsl-demo",
    "public_url": "http://demo.com",
    "objective_model": "none",
    "case_file": "board.yaml",
}

def test_the_shipped_scenarios_are_discovered_from_their_descriptor_files():
    assert set(wargames.WARGAMES) == {"board", "corp"}

def test_each_scenario_carries_the_image_it_composes_from():
    assert wargames.WARGAMES["board"]["image"] == "ghcr.io/nekonic/fsl-board"
    assert wargames.WARGAMES["corp"]["image"] == "ghcr.io/nekonic/fsl-corp"

def test_a_scenario_is_read_from_disk_not_hardcoded(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(A_SCENARIO))
    settings.FSL_SOURCE = str(tmp_path)

    discovered = wargames._discover()

    assert set(discovered) == {"demo"}
    assert discovered["demo"] == {"id": "demo", **A_SCENARIO}

def test_a_folder_without_a_descriptor_is_not_a_scenario(settings, tmp_path):
    (tmp_path / "wargames" / "half-built").mkdir(parents=True)
    settings.FSL_SOURCE = str(tmp_path)

    assert wargames._discover() == {}

@pytest.mark.parametrize("field", wargames.SCENARIO_FIELDS)
def test_a_scenario_missing_a_field_is_refused(field):
    incomplete = {k: v for k, v in A_SCENARIO.items() if k != field}

    with pytest.raises(wargames.InvalidCatalogue, match=field):
        wargames.checked_scenario(incomplete, "demo", "scenario.yaml")

def test_a_scenario_with_an_unknown_objective_model_is_refused():
    with pytest.raises(wargames.InvalidCatalogue, match="objective_model"):
        wargames.checked_scenario(
            {**A_SCENARIO, "objective_model": "guesswork"}, "demo", "scenario.yaml"
        )

def test_the_board_declares_a_lesson_start_at_paranoia_level_4_and_a_full_defense():
    board = wargames.WARGAMES["board"]

    assert wargames.defense("board", "minimal") == {"waf": {"paranoia": 4}, "suricata": "local.rules"}
    assert board["defense"]["full"]["waf"] == {"paranoia": 1}
    assert "board-normal-search-with-apostrophe" in board["lessons"][0]["cases"]

def test_a_scenario_without_a_defense_takes_the_default_and_nothing_else():
    assert wargames.defense("corp", wargames.DEFAULT_DEFENSE) is None
    with pytest.raises(wargames.UnknownWargame):
        wargames.defense("corp", "minimal")

@pytest.mark.parametrize("defense, reason", [
    ({"minimal": {"waf": {"paranoia": 7}, "suricata": "local.rules"}}, "paranoia"),
    ({"minimal": {"waf": {"paranoia": 4}, "suricata": "../../etc/passwd"}}, "suricata"),
    ({"minimal": {"waf": {"paranoia": 4}, "suricata": "missing.rules"}}, "suricata"),
    ({"minimal": {"waf": {"paranoia": 4}}}, "suricata"),
    (["minimal"], "defense"),
])
def test_a_defense_that_cannot_be_applied_is_refused_at_discovery(defense, reason):
    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames.checked_scenario({**A_SCENARIO, "defense": defense}, "demo", "scenario.yaml")

@pytest.mark.parametrize("taught, reason", [
    ({"text": "lesson.demo", "cases": ["board-normal-search", "no-such-case"]}, "no-such-case"),
    ({"text": "lesson.demo", "cases": []}, "cases"),
    ({"cases": ["board-normal-search"]}, "text"),
])
def test_a_lesson_naming_cases_the_case_file_lacks_is_refused_at_discovery(settings, tmp_path, taught, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

@pytest.mark.parametrize("defense", ["minimal", ["full"]])
def test_a_lesson_whose_defense_the_scenario_does_not_declare_is_refused_at_discovery(settings, tmp_path, defense):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "defense": defense}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="lesson's defense"):
        wargames._discover()

def test_the_board_lesson_declares_the_defense_it_starts_from_and_the_catalogue_says_so(client):
    listed = {w["id"]: w for w in client.get("/api/wargames/").json()}

    assert wargames.lesson_defense("board") == "minimal"
    assert (listed["board"]["lesson_defense"], listed["corp"]["lesson_defense"]) == ("minimal", "")

def test_the_catalogue_describes_each_scenario_for_its_card(client):
    listed = {w["id"]: w for w in client.get("/api/wargames/").json()}
    board = listed["board"]

    assert (board["category"], board["difficulty"], board["minutes"]) == ("sql-injection", "medium", 40)
    assert board["attacks"] + board["benign"] == board["cases"] and board["benign"] >= 4
    assert board["objectives"] == 3
    assert board["lesson_steps"] == len(wargames.lesson("board")["steps"]) > 0
    assert (listed["corp"]["difficulty"], listed["corp"]["lesson_steps"]) == ("hard", 0)

@pytest.mark.parametrize("card, reason", [
    ({"difficulty": "brutal"}, "difficulty"),
    ({"minutes": 0}, "minutes"),
    ({"minutes": "forty"}, "minutes"),
    ({"category": " "}, "category"),
])
def test_a_scenario_card_that_cannot_be_shown_is_refused(card, reason):
    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames.checked_scenario({**A_SCENARIO, **card}, "demo", "scenario.yaml")

def test_a_lesson_step_needs_an_id_and_its_command_is_text(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "steps": [{"command": 1}]}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="steps"):
        wargames._discover()

def test_the_board_lesson_gives_the_exact_command_for_every_terminal_step():
    commands = {step["id"]: step.get("command", "") for step in wargames.lesson("board")["steps"]}

    assert "ctl:ruleRemoveTargetById=920273;ARGS:q" in commands["exclude"]
    assert commands["exclude"].splitlines()[-1].startswith(
        "if nginx -t 2>&1 && nginx -s reload 2>&1; then echo reloaded; else cp "), (
        "the reload runs only on a file nginx accepted, and a refused file is put back"
    )
    assert commands["search"] == "", "a step in the site or in Kibana is done there, not typed"

def test_the_lesson_s_terminal_commands_name_every_file_by_its_absolute_path():
    exclusions = "/etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
    for step in wargames.lesson("board")["steps"]:
        command = step.get("command", "")
        assert "cd " not in command, "a reopened WAF terminal starts a fresh shell in /"
        mentioned = re.findall(r"/\S*REQUEST-900[^\s\"]*\.conf", command)
        assert all(name == exclusions for name in mentioned), mentioned

def test_every_lesson_step_declares_how_the_platform_checks_it(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "steps": [{"id": "a", "check": {"kind": "guess"}}]}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="need a check"):
        wargames._discover()
    assert {step["check"]["kind"] for step in wargames.lesson("board")["steps"]} <= wargames.CHECK_KINDS

def test_every_board_step_says_where_the_coach_points_so_the_console_names_no_step():
    from pathlib import Path

    console = (Path(__file__).resolve().parent.parent / "console/templates/console/blue_lesson_script.html").read_text()
    for step in wargames.lesson("board")["steps"]:
        point = step.get("point")
        assert isinstance(point, dict) and set(point) <= {"panel", "kibana", "first", "pane", "opens", "tab"}, step["id"]
        assert {"panel", "kibana", "pane"} & set(point), f"{step['id']} points at nothing"
        assert step["id"] in wargames.CHECK_KINDS or f'"{step["id"]}"' not in console, f"the console still knows step {step['id']!r} by name"
    assert "data-test-subj" not in console, "Kibana's selectors are the scenario's data, not the console's"

def test_the_catalogue_lists_each_lesson_with_what_its_card_shows(client):
    board = {w["id"]: w for w in client.get("/api/wargames/").json()}["board"]

    assert board["lessons"] == [{
        "id": "waf-exclusion", "order": 1, "title": "lesson.board.title", "goal": "lesson.board.summary",
        "minutes": 40, "level": "easy", "defense": "minimal", "prerequisites": [],
        "steps": len(wargames.lesson("board")["steps"]),
    }]
    assert wargames.lesson("board", lesson_id="waf-exclusion") == wargames.lesson("board")

@pytest.mark.parametrize("lessons, reason", [
    ([{"id": "a", "order": 1}, {"id": "a", "order": 2}], "own id"),
    ([{"id": "a", "order": 1}, {"id": "b", "order": 1}], "own whole-number order"),
    ([{"id": "Not An Id", "order": 1}], "own id"),
    ([{"id": "a", "order": 1, "prerequisites": ["missing"]}], "prerequisites"),
    ([{"id": "a", "order": 1, "prerequisites": ["a"]}], "prerequisites"),
    ([{"id": "a", "order": 1, "level": "brutal"}], "level"),
    ([{"id": "a", "order": 1, "minutes": 0}], "minutes"),
    ([], "non-empty"),
])
def test_a_lessons_list_that_cannot_be_offered_is_refused_at_discovery(settings, tmp_path, lessons, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = [{"text": "lesson.demo", "cases": ["board-normal-search"], **one} for one in lessons]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": taught}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

def test_a_scenario_still_declaring_a_single_lesson_is_refused_rather_than_silently_lessonless():
    with pytest.raises(wargames.InvalidCatalogue, match="lessons: list"):
        wargames.checked_scenario({**A_SCENARIO, "lesson": {"text": "lesson.demo"}}, "demo", "scenario.yaml")
