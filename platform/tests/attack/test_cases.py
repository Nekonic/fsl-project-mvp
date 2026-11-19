import pytest

from attack.models import Action, ToolRun
from tests.attack.conftest import codes, url
from tests.attack.fakes import RU

pytestmark = pytest.mark.django_db


def test_the_case_list_holds_the_declared_attack_cases_only(as_attacker, attacker):
    listed = as_attacker.get(url(attacker.round, "cases/")).json()

    names = {case["case"]: case for case in listed}
    assert "board-sqli-search" in names and names["board-sqli-search"]["kind"] == "http"
    assert names["board-sqli-orderby-sqlmap"]["kind"] == "tool"
    assert all(case["malicious"] is True for case in listed)
    assert not any(name.startswith("board-normal") for name in names)


def test_an_http_case_fires_from_the_box_with_its_marker_and_is_charged_on_the_spot(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "cases/"), {"case": "board-sqli-search"}, format="json")

    assert answer.status_code == 202
    body = answer.json()
    action = Action.objects.get(pk=body["action"])
    assert (action.kind, action.case_id, action.malicious, action.expect) == ("case", "board-sqli-search", True, "SQL")
    assert (action.marker != action.case_id, action.source_ip, action.charged) == (True, RU, True)
    [fired] = cloud.box.matching("http_code=")
    assert f"X-Request-ID: {action.marker}" in fired.argv and "Host: board.com" in fired.argv
    assert cloud.launched == ["ru"]
    assert (body["run"], body["status"], body["hp"]["left"]) == (None, 200, 99)


def test_a_tool_case_becomes_a_tool_run_with_the_marker_in_its_argv(as_attacker, attacker):
    answer = as_attacker.post(url(attacker.round, "cases/"), {"case": "board-sqli-orderby-sqlmap"}, format="json")

    body = answer.json()
    run = ToolRun.objects.get(pk=body["run"])
    action = Action.objects.get(pk=body["action"])
    assert (answer.status_code, run.tool, action.kind, action.charged) == (202, "sqlmap", "case", False)
    assert f"--headers=X-Request-ID: {action.marker}" in run.argv
    assert body["hp"]["left"] == 100


def test_a_benign_case_is_the_platform_s_to_fire_and_unknown_to_the_attacker(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "cases/"), {"case": "board-normal-search"}, format="json")

    assert (answer.status_code, codes(answer)) == (404, ["unknown_case"])
    assert cloud.box.matching("http_code=") == []
