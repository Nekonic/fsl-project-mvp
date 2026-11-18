from pathlib import Path

import pytest
import yaml

import wargames
from redteam.harness import load_cases

CASES_DIR = Path(__file__).resolve().parents[2] / "redteam/cases"
REQUEST = {"method": "GET", "path": "/"}

def a_case(**overrides):
    return {"name": "probe", "malicious": True, "request": REQUEST, **overrides}

@pytest.mark.parametrize("path", sorted(CASES_DIR.glob("*.yaml")), ids=lambda path: path.name)
def test_every_case_file_shipped_passes_the_catalogue_check(path):
    assert wargames.checked(load_cases(path), path)

MISSING = object()

@pytest.mark.parametrize("given", ["false", "true", 0, 1, None, MISSING])
def test_a_case_that_is_not_plainly_an_attack_or_not_is_refused(given):
    case = {key: value for key, value in a_case(malicious=given).items() if value is not MISSING}

    with pytest.raises(wargames.InvalidCatalogue, match="probe"):
        wargames.checked([case], "cases.yaml")

def test_two_cases_under_one_name_are_refused():
    with pytest.raises(wargames.InvalidCatalogue, match="probe"):
        wargames.checked([a_case(), a_case(malicious=False)], "cases.yaml")

@pytest.mark.parametrize("sends", [{"tool": "sqlmap"}, {"request": MISSING}], ids=["both", "neither"])
def test_a_case_must_either_send_a_request_or_run_a_tool(sends):
    case = {key: value for key, value in a_case(**sends).items() if value is not MISSING}

    with pytest.raises(wargames.InvalidCatalogue, match="probe"):
        wargames.checked([case], "cases.yaml")

def test_the_console_catalogue_is_checked_before_it_is_used(settings, tmp_path):
    (tmp_path / "board.yaml").write_text(yaml.safe_dump([a_case(malicious="false")]))
    settings.WARGAME_CASES_DIR = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="probe"):
        wargames.cases("board")
