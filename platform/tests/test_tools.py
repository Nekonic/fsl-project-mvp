import os
import subprocess
import sys

import pytest

from redteam.tools import (
    TOOL_IMAGE,
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

def test_the_case_names_the_image_and_the_tool_and_only_a_marker_case_carries_the_marker():
    assert tool_argv(CASE, INTERNAL_TARGET) == (TOOL_IMAGE, [
        "sqlmap", "-u", f"{INTERNAL_TARGET}/rest/products/search?q=1", "--batch",
        "--headers=X-Request-ID: abc-123",
    ])
    _, window = tool_argv(dict(CASE, correlation="window"), INTERNAL_TARGET)
    assert not any("X-Request-ID" in part for part in window)

def test_tool_case_in_the_default_file_declares_args():
    from pathlib import Path

    from redteam.harness import load_cases

    cases = load_cases(Path(__file__).resolve().parents[2] / "redteam/cases/board.yaml")
    tool_cases = [c for c in cases if is_tool_case(c)]

    assert tool_cases, "no tool: cases at all"
    for case in tool_cases:
        assert case["args"], f"{case['name']}  has no args"
        assert any("{target}" in a for a in case["args"]), (
            f"{case['name']}  does not use {{target}}, so its target is hardcoded"
        )

def test_the_tamper_variant_skips_the_heuristic_probe_that_a_dropped_connection_ends_the_run_on():
    from pathlib import Path

    from redteam.harness import load_cases

    cases = {c["name"]: c for c in load_cases(Path(__file__).resolve().parents[2] / "redteam/cases/board.yaml")}

    assert "--skip-heuristics" in cases["board-sqli-orderby-sqlmap-tamper"]["args"], (
        "from paranoia level 2 a board 500 is refused after its headers are sent and nginx drops the "
        "connection; when the tampered heuristic probe drew one, sqlmap stopped after one request and "
        "VERIFY read the variant as inconclusive at the level the lesson names as the answer"
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

def test_core_does_not_start_anything_itself():
    import pathlib

    from redteam import harness

    source = pathlib.Path(harness.__file__).read_text()

    assert "subprocess" not in source, (
        "redteam/harness.py is gated core and shelled out to docker run, so "
        "the hypothesis could not be carried anywhere without a daemon"
    )

def test_sqlmap_s_conclusions_are_its_verdict_lines_without_the_clock():
    from pathlib import Path

    from redteam.tools import conclusions

    fixtures = Path(__file__).resolve().parent / "fixtures"
    dumped = conclusions((fixtures / "sqlmap-orderby-dump.out").read_text())
    missing = conclusions((fixtures / "sqlmap-host-missing.out").read_text())

    assert any("identified the following injection point" in line for line in dumped)
    assert all(not line.startswith("[0") for line in dumped)
    assert missing == ["[CRITICAL] host 'nowhere' does not exist"]
    assert conclusions("") == []

def test_the_tool_image_defaults_to_the_attacker_host_the_range_declares(settings):
    from tests.conftest import REPO_ROOT

    environment = {name: value for name, value in os.environ.items() if name != "FSL_TOOL_IMAGE"}
    printed = subprocess.run(
        [sys.executable, "-c", "from redteam.tools import TOOL_IMAGE; print(TOOL_IMAGE)"],
        cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert printed == settings.RANGE.roles["attacker"], (
        "the OpenStack launcher runs a tool only on the attacker host the range declares"
    )
