import pytest

from attack.tools import (
    FREE_TOOLS,
    UnknownTool,
    free_argv,
    is_tool_case,
    tool_argv,
)

CASE = {
    "case_id": "abc-123",
    "name": "sqlmap-probe",
    "malicious": True,
    "correlation": "marker",
    "tool": "sqlmap",
    "args": ["-u", "{target}/rest/products/search?q=1", "--batch"],
}
INTERNAL_TARGET = "http://waf:8080"

def test_the_case_names_the_image_and_the_tool_and_only_a_marker_case_carries_the_marker_and_its_own_sqlmap_output():
    from attack.box import SQLMAP_RUNS

    assert tool_argv(CASE, INTERNAL_TARGET, SQLMAP_RUNS) == [
        "sqlmap", "-u", f"{INTERNAL_TARGET}/rest/products/search?q=1", "--batch",
        "--headers=X-Request-ID: abc-123", "--output-dir=/tmp/sqlmap-runs/abc-123",
    ]
    window = tool_argv(dict(CASE, correlation="window"), INTERNAL_TARGET, SQLMAP_RUNS)
    assert not any("X-Request-ID" in part or "--output-dir" in part for part in window)

def test_tool_case_in_the_default_file_declares_args():
    from pathlib import Path

    from attack.firing import load_cases

    cases = load_cases(Path(__file__).resolve().parents[3] / "redteam/cases/board.yaml")
    tool_cases = [c for c in cases if is_tool_case(c)]

    assert tool_cases, "no tool: cases at all"
    for case in tool_cases:
        assert case["args"], f"{case['name']}  has no args"
        assert any("{target}" in a for a in case["args"]), (
            f"{case['name']}  does not use {{target}}, so its target is hardcoded"
        )

def test_the_tamper_variant_skips_the_heuristic_probe_that_a_dropped_connection_ends_the_run_on():
    from pathlib import Path

    from attack.firing import load_cases

    cases = {c["name"]: c for c in load_cases(Path(__file__).resolve().parents[3] / "redteam/cases/board.yaml")}

    assert "--skip-heuristics" in cases["board-sqli-orderby-sqlmap-tamper"]["args"], (
        "from paranoia level 2 a board 500 is refused after its headers are sent and nginx drops the "
        "connection; when the tampered heuristic probe drew one, sqlmap stopped after one request and "
        "VERIFY read the variant as inconclusive at the level the lesson names as the answer"
    )

def launcher(exit_code, output=""):
    from range.runner import Ran

    def launch(argv, timeout=600.0):
        launch.started.append(argv)
        return Ran(exit_code=exit_code, output=output)

    launch.started = []
    return launch

def test_missing_tool_image_raises_instead_of_being_swallowed():
    from attack.firing import fire_tool
    from attack.tools import ToolUnavailable

    with pytest.raises(ToolUnavailable, match="did not run"):
        fire_tool(
            dict(CASE), INTERNAL_TARGET,
            launcher(125, "Unable to find image 'cr-kali:latest' locally"),
        )

def test_tool_reporting_a_failed_scan_is_not_an_error():
    from attack.firing import fire_tool

    fire_tool(
        dict(CASE), INTERNAL_TARGET,
        launcher(1, "all tested parameters do not appear to be injectable"),
    )

def test_core_does_not_start_anything_itself():
    import pathlib

    from attack import firing as harness

    source = pathlib.Path(harness.__file__).read_text()

    assert "subprocess" not in source, (
        "redteam/harness.py is gated core and shelled out to docker run, so "
        "the hypothesis could not be carried anywhere without a daemon"
    )

def test_sqlmap_s_conclusions_are_its_verdict_lines_without_the_clock():
    from pathlib import Path

    from attack.tools import conclusions

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    dumped = conclusions((fixtures / "sqlmap-orderby-dump.out").read_text())
    missing = conclusions((fixtures / "sqlmap-host-missing.out").read_text())

    assert any("identified the following injection point" in line for line in dumped)
    assert all(not line.startswith("[0") for line in dumped)
    assert missing == ["[CRITICAL] host 'nowhere' does not exist"]
    assert conclusions("") == []

def test_a_free_tool_is_one_the_box_offers_and_a_marker_rides_on_curl_and_sqlmap():
    assert free_argv("curl", ["-s", "http://board.com/"], "action-3") == [
        "curl", "-H", "X-Request-ID: action-3", "-s", "http://board.com/"]
    assert free_argv("nmap", ["-p", "80", "board.com"], "action-4") == ["nmap", "-p", "80", "board.com"]
    assert "sqlmap" in FREE_TOOLS
    with pytest.raises(UnknownTool) as unknown:
        free_argv("bash", ["-c", "id"])
    assert unknown.value.code == "unknown_tool" and unknown.value.status == 404
    with pytest.raises(ValueError):
        free_argv("curl", "http://board.com/")
