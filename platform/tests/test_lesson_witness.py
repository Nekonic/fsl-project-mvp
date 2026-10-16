import pytest
from types import SimpleNamespace

from redteam import harness, tools


def test_an_http_case_reports_the_status_the_target_answered_with():
    image, argv = tools.curl_argv(
        SimpleNamespace(method="GET", headers={}, body=None, url="http://board.com/"), 15,
    )

    assert argv[argv.index("-w") + 1] == "http_code=%{http_code}\n"
    assert tools.status("http_code=403\n") == 403
    assert tools.status("curl: (28) Operation timed out after 15001 milliseconds") == 0

@pytest.mark.parametrize("case, target", [
    ({"case_id": "c", "name": "board-normal-sort", "correlation": "marker",
      "request": {"method": "GET", "path": "/", "params": {"sort": "-created_at"}}}, "http://board.com"),
    ({"case_id": "c", "name": "sqlmap", "correlation": "marker", "tool": "sqlmap", "args": []}, None),
], ids=["http", "tool"])
def test_firing_hands_back_what_the_attacker_box_printed(case, target):
    printed = SimpleNamespace(exit_code=0, output="http_code=200\n")
    launch = lambda image, argv, timeout=None: printed

    assert (harness.fire(case, launch, target) if target else harness.fire(case, launch)) is printed


FIXTURES = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"

def test_a_real_sqlmap_dump_of_the_board_matches_the_board_s_own_snapshot():
    import json

    from api import loot

    output = (FIXTURES / "sqlmap-orderby-dump.out").read_text()
    truth = json.loads((FIXTURES / "board-auth-users.json").read_text())

    assert tools.dumped(output) == sorted(truth.items())
    assert loot.matched(tools.dumped(output), truth) == set(truth)
    assert not tools.found_not_injectable(0, output), "a run that dumped rows is no evidence of a block"

def test_sqlmap_concluding_not_injectable_is_a_conclusion_and_a_missing_host_is_not():
    held = (FIXTURES / "sqlmap-not-injectable.out").read_text()
    lost = (FIXTURES / "sqlmap-host-missing.out").read_text()

    assert tools.dumped(held) == [] and tools.found_not_injectable(0, held)
    assert not tools.found_not_injectable(0, lost)
    assert not tools.found_not_injectable(1, held), "a non-zero exit proves nothing"

@pytest.mark.parametrize("capture", [
    "sqlmap-waf-stock-pl4.out", "sqlmap-waf-tamper-pl4.out",
    "sqlmap-waf-stock-pl4-excl.out", "sqlmap-waf-tamper-pl4-excl.out",
])
def test_sqlmap_turned_away_by_the_waf_is_a_conclusion_not_a_tool_failure(capture):
    output = (FIXTURES / capture).read_text()

    assert tools.dumped(output) == []
    assert tools.found_not_injectable(0, output), (
        "behind the WAF sqlmap reports the WAF, a run of 403s and, with a random "
        "User-Agent, a few dropped connections where ModSecurity cut the board's "
        "500 responses; it still tested everything and concluded not injectable"
    )
    assert tools.forbidden(output) > 2000

def test_a_connection_failure_that_stops_sqlmap_before_its_conclusion_proves_nothing():
    output = (FIXTURES / "sqlmap-waf-tamper-pl4.out").read_text()
    cut = output[:output.index("[INFO] testing for SQL injection")] + "[*] ending @ 06:38:44 /2026-10-10/\n"

    assert "unable to connect" in cut
    assert not tools.found_not_injectable(0, cut)
