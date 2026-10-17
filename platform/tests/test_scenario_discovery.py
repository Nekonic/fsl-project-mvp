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

def test_a_scenario_is_read_from_disk_not_hardcoded(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(A_SCENARIO))
    settings.FSL_SOURCE = str(tmp_path)

    discovered = wargames._discover()

    assert set(discovered) == {"demo"}
    assert discovered["demo"] == {"id": "demo", **A_SCENARIO}

@pytest.mark.parametrize("field", wargames.SCENARIO_FIELDS)
def test_a_scenario_missing_a_field_is_refused(field):
    incomplete = {k: v for k, v in A_SCENARIO.items() if k != field}

    with pytest.raises(wargames.InvalidCatalogue, match=field):
        wargames.checked_scenario(incomplete, "demo", "scenario.yaml")

@pytest.mark.parametrize("changed, reason", [
    ({"objective_model": "guesswork"}, "objective_model"),
    ({"defense": {"minimal": {"waf": {"paranoia": 7}, "suricata": "local.rules"}}}, "paranoia"),
    ({"defense": {"minimal": {"waf": {"paranoia": 4}, "suricata": "../../etc/passwd"}}}, "suricata"),
    ({"defense": {"minimal": {"waf": {"paranoia": 4}, "suricata": "missing.rules"}}}, "suricata"),
    ({"defense": {"minimal": {"waf": {"paranoia": 4}}}}, "suricata"),
    ({"defense": ["minimal"]}, "defense"),
])
def test_a_scenario_that_cannot_be_applied_is_refused_at_discovery(changed, reason):
    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames.checked_scenario({**A_SCENARIO, **changed}, "demo", "scenario.yaml")

ONE = {"id": "demo", "order": 1, "text": "lesson.demo", "cases": ["board-normal-search"]}

@pytest.mark.parametrize("foundations, reason", [
    ([dict(ONE, cases=["board-normal-search", "no-such-case"])], "no-such-case"),
    ([dict(ONE, cases=[])], "cases"),
    ([{key: value for key, value in ONE.items() if key != "text"}], "text"),
    ([dict(ONE, defense="minimal")], "lesson's defense"),
    ([dict(ONE, defense=["full"])], "lesson's defense"),
    ([dict(ONE, steps=[{"command": 1}])], "steps"),
    ([dict(ONE, steps=[{"id": "a", "check": {"kind": "guess"}}])], "need a check"),
    ([dict(ONE, id="a"), dict(ONE, id="a", order=2)], "own id"),
    ([dict(ONE, id="a"), dict(ONE, id="b")], "own whole-number order"),
    ([dict(ONE, id="Not An Id")], "own id"),
    ([dict(ONE, id="a", prerequisites=["missing"])], "prerequisites"),
    ([dict(ONE, id="a", prerequisites=["a"])], "prerequisites"),
    ([], "non-empty"),
])
def test_a_foundations_list_that_cannot_be_offered_is_refused_at_discovery(settings, tmp_path, foundations, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": foundations}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

def test_the_catalogue_lists_each_foundation_with_what_its_card_shows(client):
    listed = {w["id"]: w for w in client.get("/api/wargames/").json()}
    board = listed["board"]

    assert board["foundations"]
    for card in board["foundations"]:
        assert set(card) == {"id", "order", "title", "goal", "minutes", "level", "defense", "prerequisites", "steps",
                             "step_ids", "learns"}, card["id"]
        assert card["defense"] == wargames.lesson_defense("board", card["id"])
        assert card["steps"] == len(wargames.lesson("board", lesson_id=card["id"])["steps"]) > 0
    assert board["attacks"] + board["benign"] == board["cases"] and board["benign"] >= 4
    assert listed["corp"]["foundations"] == []

def test_the_waf_step_s_command_names_the_declared_exclusion_file(settings):
    [step] = [step for step in wargames.lesson("board", lesson_id="f6")["steps"] if step["id"] == "excluded"]

    assert step["command"] == f"grep -n ruleRemove {settings.FSL_WAF.rules}"
