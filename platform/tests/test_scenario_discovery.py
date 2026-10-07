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
