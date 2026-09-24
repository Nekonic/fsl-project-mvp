import pytest

from redteam.tools import (
    TOOL_IMAGE,
    UnsupportedTool,
    is_tool_case,
    tool_argv,
)

def build_tool_command(case, target_url):
    image, argv = tool_argv(case, target_url)
    return [image, *argv]

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

def test_the_case_names_the_image_and_the_tool_and_nothing_else():
    image, argv = tool_argv(CASE, INTERNAL_TARGET)

    assert image == TOOL_IMAGE
    assert argv[0] == "sqlmap"

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


def launcher(exit_code, output=""):
    from range.ports import Ran

    def launch(image, argv, timeout=600.0):
        launch.started.append((image, argv))
        return Ran(exit_code=exit_code, output=output)

    launch.started = []
    return launch

def test_missing_tool_image_raises_instead_of_being_swallowed():
    from redteam.harness import fire_tool
    from redteam.tools import ToolUnavailable

    with pytest.raises(ToolUnavailable, match="fsl-kali"):
        fire_tool(
            dict(CASE), INTERNAL_TARGET,
            launcher(125, "Unable to find image 'fsl-kali:latest' locally"),
        )

def test_tool_reporting_a_failed_scan_is_not_an_error():
    from redteam.harness import fire_tool

    fire_tool(
        dict(CASE), INTERNAL_TARGET,
        launcher(1, "all tested parameters do not appear to be injectable"),
    )


def test_nothing_in_the_tool_command_names_a_substrate():
    image, argv = tool_argv(
        {"name": "t", "tool": "sqlmap", "args": ["-u", "{target}/x"]},
        "http://waf-edge-hk:8080",
    )

    assert "docker" not in [image, *argv], (
        "the command was a docker run, so an attack could only ever be fired "
        "from something with a Docker daemon on it"
    )
    assert not any("--network" in str(part) for part in argv), (
        "which network a tool runs on was recovered by cutting 'waf-' off the "
        "target's hostname and pasting the project back on, after the origin "
        "id it was built from had already been thrown away"
    )

def test_core_does_not_start_anything_itself():
    import pathlib

    from redteam import harness

    source = pathlib.Path(harness.__file__).read_text()

    assert "subprocess" not in source, (
        "redteam/harness.py is gated core and shelled out to docker run, so "
        "the hypothesis could not be carried anywhere without a daemon"
    )
