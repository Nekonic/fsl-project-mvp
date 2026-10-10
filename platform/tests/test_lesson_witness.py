import pytest
from types import SimpleNamespace

from redteam import harness, tools

DUMP = """[04:12:09] [INFO] fetching entries of column(s) 'password,username' for table 'auth_user' in database 'board'
Database: board
Table: auth_user
[3 entries]
+----------+-------------------------------------------+
| username | password                                  |
+----------+-------------------------------------------+
| admin    | pbkdf2_sha256$870000$aa$hash-of-admin=    |
| jiwoo    | pbkdf2_sha256$870000$bb$hash-of-jiwoo=    |
| minseo   | pbkdf2_sha256$870000$cc$hash-of-minseo=   |
+----------+-------------------------------------------+
"""

HELD = """[04:12:01] [CRITICAL] all tested parameters do not appear to be injectable.
[04:12:01] [WARNING] HTTP error codes detected during run:
403 (Forbidden) - 94 times
"""

def test_the_rows_sqlmap_dumped_are_read_as_username_and_hash():
    assert tools.dumped(DUMP) == [
        ("admin", "pbkdf2_sha256$870000$aa$hash-of-admin="),
        ("jiwoo", "pbkdf2_sha256$870000$bb$hash-of-jiwoo="),
        ("minseo", "pbkdf2_sha256$870000$cc$hash-of-minseo="),
    ]

def test_the_columns_are_read_by_their_header_not_their_order():
    swapped = "| password | username |\n| h1 | admin |\n"

    assert tools.dumped(swapped) == [("admin", "h1")]

def test_a_run_that_dumped_nothing_leaked_nothing():
    assert tools.dumped(HELD) == []
    assert tools.dumped("") == []

def test_the_403s_sqlmap_reports_are_counted():
    assert tools.forbidden(HELD) == 94
    assert tools.forbidden(DUMP) == 0

def test_an_http_case_reports_the_status_the_target_answered_with():
    image, argv = tools.curl_argv(
        SimpleNamespace(method="GET", headers={}, body=None, url="http://board.com/"), 15,
    )

    assert argv[argv.index("-w") + 1] == "http_code=%{http_code}\n"
    assert tools.status("http_code=403\n") == 403
    assert tools.status("curl: (28) Operation timed out after 15001 milliseconds") == 0

def test_firing_hands_back_what_the_attacker_box_printed():
    printed = SimpleNamespace(exit_code=0, output="http_code=200\n")
    case = {
        "case_id": "c", "name": "board-normal-sort", "correlation": "marker",
        "request": {"method": "GET", "path": "/", "params": {"sort": "-created_at"}},
    }

    assert harness.fire(case, lambda image, argv, timeout=None: printed, "http://board.com") is printed

def test_firing_a_tool_hands_back_its_output():
    printed = SimpleNamespace(exit_code=0, output=DUMP)
    case = {"case_id": "c", "name": "sqlmap", "correlation": "marker", "tool": "sqlmap", "args": []}

    assert harness.fire(case, lambda image, argv, timeout=None: printed) is printed


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
