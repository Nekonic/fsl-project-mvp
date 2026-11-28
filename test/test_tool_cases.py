import pytest


@pytest.fixture(scope="module")
def fired(origins_round):
    sent = origins_round["tool"]
    assert sent.status == 202, sent.text
    return sent.body


def test_a_case_that_runs_a_tool_becomes_a_tool_run_on_the_attacker_box(fired, origins_round):
    assert fired["run"] is not None, "a tool case answered like an HTTP case"
    runs = {run["run"]: run for run in origins_round["tools"]["runs"]}

    assert runs[fired["run"]]["tool"] == "sqlmap", (
        "nothing else in this suite starts a tool, so the whole path from the "
        "console to the tool on the attacker box was unguarded"
    )
    assert origins_round["tool_run"]["done"] and origins_round["tool_run"]["exit_code"] is not None, (
        origins_round["tool_run"])


def test_a_tool_the_box_does_not_have_is_refused(origins_round):
    refused = origins_round["unknown_tool"]

    assert refused.status == 404 and "unknown_tool" in refused.codes, (
        f"the tool was started anyway: {refused.status} {refused.text[:200]}"
    )
