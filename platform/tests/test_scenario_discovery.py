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

def test_the_board_declares_a_minimal_and_a_full_defense_and_each_foundation_starts_from_one_it_declares():
    board = wargames.WARGAMES["board"]

    assert wargames.defense("board", "minimal") == {"waf": {"paranoia": 4}, "suricata": "local.rules"}
    assert board["defense"]["full"]["waf"] == {"paranoia": 1}
    assert {taught["defense"] for taught in wargames.foundations("board")} <= set(board["defense"])

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
def test_a_foundation_naming_cases_the_case_file_lacks_is_refused_at_discovery(settings, tmp_path, taught, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

@pytest.mark.parametrize("defense", ["minimal", ["full"]])
def test_a_foundation_whose_defense_the_scenario_does_not_declare_is_refused_at_discovery(settings, tmp_path, defense):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "defense": defense}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="lesson's defense"):
        wargames._discover()

def test_each_foundation_declares_the_defense_it_starts_from_and_the_catalogue_says_so(client):
    listed = {w["id"]: w for w in client.get("/api/wargames/").json()}

    assert (wargames.lesson_defense("board", "f1"), wargames.lesson_defense("board", "f6")) == ("full", "missed")
    assert [card["defense"] for card in listed["board"]["foundations"]] == [
        wargames.lesson_defense("board", lesson_id) for lesson_id in wargames.taught_ids("board")]
    assert listed["corp"]["foundations"] == []

def test_the_catalogue_describes_each_scenario_for_its_card(client):
    listed = {w["id"]: w for w in client.get("/api/wargames/").json()}
    board = listed["board"]

    assert (board["category"], board["difficulty"], board["minutes"]) == ("sql-injection", "medium", 40)
    assert board["attacks"] + board["benign"] == board["cases"] and board["benign"] >= 4
    assert board["objectives"] == 3
    assert [card["steps"] for card in board["foundations"]] == [
        len(wargames.lesson("board", lesson_id=lesson_id)["steps"]) for lesson_id in wargames.taught_ids("board")]
    assert all(card["steps"] > 0 for card in board["foundations"])
    assert (listed["corp"]["difficulty"], listed["corp"]["foundations"]) == ("hard", [])

@pytest.mark.parametrize("card, reason", [
    ({"difficulty": "brutal"}, "difficulty"),
    ({"minutes": 0}, "minutes"),
    ({"minutes": "forty"}, "minutes"),
    ({"category": " "}, "category"),
])
def test_a_scenario_card_that_cannot_be_shown_is_refused(card, reason):
    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames.checked_scenario({**A_SCENARIO, **card}, "demo", "scenario.yaml")

def test_a_foundation_step_needs_an_id_and_its_command_is_text(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "steps": [{"command": 1}]}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="steps"):
        wargames._discover()

def stepped(wargame_id="board"):
    return [wargames.lesson(wargame_id, lesson_id=lesson_id) for lesson_id in [
        *wargames.taught_ids(wargame_id), *(one["id"] for one in wargames.stepped_scenarios(wargame_id))]]

def test_the_foundation_gives_the_exact_command_for_its_terminal_step_and_none_for_a_step_done_elsewhere(settings):
    commands = {(taught["id"], step["id"]): step.get("command", "") for taught in stepped() for step in taught["steps"]}

    assert commands[("f6", "excluded")] == f"cat {settings.FSL_WAF.rules}"
    assert commands[("f5", "attack")] == commands[("f4", "find")] == "", "a step in the site or in Kibana is done there, not typed"
    assert [key for key, command in commands.items() if command] == [("f6", "excluded")]

def test_the_lessons_terminal_commands_name_every_file_by_its_absolute_path():
    for taught in stepped():
        for step in taught["steps"]:
            command = step.get("command", "")
            assert "cd " not in command, "a reopened WAF terminal starts a fresh shell in /"
            named = [word for word in command.split()[1:] if "/" in word or "." in word]
            assert all(word.startswith("/") for word in named), (taught["id"], step["id"], named)

def test_every_foundation_step_declares_how_the_platform_checks_it(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = {"text": "lesson.demo", "cases": ["board-normal-search"], "steps": [{"id": "a", "check": {"kind": "guess"}}]}
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": [{"id": "demo", "order": 1, **taught}]}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="need a check"):
        wargames._discover()
    assert {step["check"]["kind"] for taught in stepped() for step in taught["steps"]} <= wargames.CHECK_KINDS

def test_every_board_step_says_where_the_coach_points_so_the_console_names_no_step():
    from pathlib import Path

    console = (Path(__file__).resolve().parent.parent / "console/templates/console/blue_lesson_script.html").read_text()
    for taught in stepped():
        for step in taught["steps"]:
            point = step.get("point")
            assert isinstance(point, dict) and set(point) <= {"panel", "kibana", "first", "pane", "opens", "tab"}, step["id"]
            assert {"panel", "kibana", "pane"} & set(point), f"{step['id']} points at nothing"
            assert step["id"] in wargames.CHECK_KINDS or f'"{step["id"]}"' not in console, f"the console still knows step {step['id']!r} by name"
    assert "data-test-subj" not in console, "Kibana's selectors are the scenario's data, not the console's"

def test_the_catalogue_lists_each_foundation_with_what_its_card_shows(client):
    board = {w["id"]: w for w in client.get("/api/wargames/").json()}["board"]

    assert [card["id"] for card in board["foundations"]] == ["f1", "f2", "f3", "f4", "f5", "f6"], (
        "the recommended path, in foundation order")
    assert next(card for card in board["foundations"] if card["id"] == "f6") == {
        "id": "f6", "order": 6, "title": "lesson.miss.title", "goal": "lesson.miss.summary",
        "minutes": 25, "level": "medium", "defense": "missed", "prerequisites": ["f5"],
        "steps": len(wargames.lesson("board", lesson_id="f6")["steps"]), "learns": "lesson.miss.learns",
    }
    assert wargames.lesson("board", lesson_id="f6")["group"] == "foundations"

@pytest.mark.parametrize("foundations, reason", [
    ([{"id": "a", "order": 1}, {"id": "a", "order": 2}], "own id"),
    ([{"id": "a", "order": 1}, {"id": "b", "order": 1}], "own whole-number order"),
    ([{"id": "Not An Id", "order": 1}], "own id"),
    ([{"id": "a", "order": 1, "prerequisites": ["missing"]}], "prerequisites"),
    ([{"id": "a", "order": 1, "prerequisites": ["a"]}], "prerequisites"),
    ([{"id": "a", "order": 1, "level": "brutal"}], "level"),
    ([{"id": "a", "order": 1, "minutes": 0}], "minutes"),
    ([], "non-empty"),
])
def test_a_foundations_list_that_cannot_be_offered_is_refused_at_discovery(settings, tmp_path, foundations, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = [{"text": "lesson.demo", "cases": ["board-normal-search"], **one} for one in foundations]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": taught}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()
