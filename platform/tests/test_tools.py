import pytest

from redteam.tools import (
    TOOL_IMAGE,
    TOOL_NETWORK,
    UnsupportedTool,
    build_tool_command,
    is_tool_case,
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

def test_is_tool_case_detects_the_tool_field():
    assert is_tool_case(CASE) is True
    assert is_tool_case({"request": {"path": "/"}}) is False

def test_command_runs_the_tool_image_on_the_stack_network():
    command = build_tool_command(CASE, INTERNAL_TARGET)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == TOOL_NETWORK
    assert TOOL_IMAGE in command
    assert "sqlmap" in command

def test_target_placeholder_is_substituted():
    command = build_tool_command(CASE, INTERNAL_TARGET)

    assert f"{INTERNAL_TARGET}/rest/products/search?q=1" in command

def test_marker_header_is_injected_for_marker_cases():
    command = build_tool_command(CASE, INTERNAL_TARGET)

    assert "--headers=X-FSL-Case: abc-123" in command

def test_marker_header_is_omitted_for_window_cases():
    case = dict(CASE, correlation="window")

    command = build_tool_command(case, INTERNAL_TARGET)

    assert not any("X-FSL-Case" in part for part in command)

def test_unknown_tool_is_rejected():
    case = dict(CASE, tool="metasploit")

    with pytest.raises(UnsupportedTool, match="metasploit"):
        build_tool_command(case, INTERNAL_TARGET)

def test_tool_case_in_the_default_file_declares_args():
    from pathlib import Path

    from redteam.harness import load_cases

    cases = load_cases(Path(__file__).resolve().parents[2] / "redteam/cases/default.yaml")
    tool_cases = [c for c in cases if is_tool_case(c)]

    assert tool_cases, "no tool: cases at all"
    for case in tool_cases:
        assert case["args"], f"{case['name']}  has no args"
        assert any("{target}" in a for a in case["args"]), (
            f"{case['name']}  does not use {{target}}, so its target is hardcoded"
        )

                                                                              
 
                                                                          
                                                                            
                                                                      

def test_missing_tool_image_raises_instead_of_being_swallowed():
    import subprocess
    from unittest.mock import patch

    from redteam.harness import fire_tool
    from redteam.tools import ToolUnavailable

    failure = subprocess.CompletedProcess(
        args=["docker"],
        returncode=125,
        stdout="",
        stderr="Unable to find image 'fsl-kali:latest' locally",
    )

    with patch("redteam.harness.subprocess.run", return_value=failure):
        with pytest.raises(ToolUnavailable, match="fsl-kali"):
            fire_tool(dict(CASE), INTERNAL_TARGET)

def test_tool_reporting_a_failed_scan_is_not_an_error():
                                                                         
                                       
    import subprocess
    from unittest.mock import patch

    from redteam.harness import fire_tool

    scan_failed = subprocess.CompletedProcess(
        args=["docker"],
        returncode=1,
        stdout="all tested parameters do not appear to be injectable",
        stderr="",
    )

    with patch("redteam.harness.subprocess.run", return_value=scan_failed):
        fire_tool(dict(CASE), INTERNAL_TARGET)                

                                                                            

def test_a_tool_attacking_through_another_origin_runs_on_that_network():
                                                                              
                                                                         
                                                                            
                                                      
    command = build_tool_command(
        {"name": "t", "tool": "sqlmap", "args": ["-u", "{target}/x"]},
        "http://waf-edge-hk:8080",
    )

    assert command[command.index("--network") + 1] == "fsl_edge-hk"

def test_a_tool_attacking_through_the_front_door_runs_where_it_always_did():
    command = build_tool_command(
        {"name": "t", "tool": "sqlmap", "args": ["-u", "{target}/x"]},
        "http://waf-edge:8080",
    )

    assert command[command.index("--network") + 1] == "fsl_edge"
