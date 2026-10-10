import pytest
import yaml

import wargames

A_SCENARIO = {
    "name": "Demo",
    "description": "A scenario discovered from disk.",
    "image": "fsl/demo:mvp",
    "public_url": "http://demo.com",
    "objective_model": "none",
    "case_file": "board.yaml",
}

def test_the_shipped_scenarios_are_discovered_from_their_descriptor_files():
    assert set(wargames.WARGAMES) == {"board", "corp"}

def test_each_scenario_carries_the_image_it_composes_from():
    assert wargames.WARGAMES["board"]["image"] == "fsl/board:mvp"
    assert wargames.WARGAMES["corp"]["image"] == "fsl/corp:mvp"

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
    assert "board-normal-search-with-apostrophe" in board["lesson"]["cases"]

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
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lesson": taught}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

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
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lesson": taught}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="steps"):
        wargames._discover()

def test_the_board_lesson_gives_the_exact_command_for_every_terminal_step():
    commands = {step["id"]: step.get("command", "") for step in wargames.lesson("board")["steps"]}

    assert "ctl:ruleRemoveTargetById=920273;ARGS:q" in commands["edit"]
    assert commands["apply"] == "nginx -t && nginx -s reload"
    assert commands["alerts"] == "", "a Kibana step is a click, not a command"
