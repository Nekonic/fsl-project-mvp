import pytest
import requests

from conftest import PLATFORM_URL

CASE = "sqlmap-boolean-blind"

@pytest.fixture(scope="module")
def fired(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": CASE, "origin": "edge-hk"}, timeout=900,
    )
    assert sent.status_code == 201, sent.text
    return sent.json()

def test_a_case_that_runs_a_tool_gets_the_tool_run(fired):
    assert fired["meta"]["tool"] == "sqlmap", (
        "nothing else in this suite starts a tool, so the whole path from the "
        "console to a throwaway host on an origin's network was unguarded"
    )

def test_the_tool_leaves_by_the_origin_it_was_told_to(fired):
    assert fired["meta"]["origin"] == "edge-hk"

def test_an_origin_the_range_does_not_have_is_refused(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]

    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": CASE, "origin": "dmz"}, timeout=120,
    )

    assert sent.status_code == 404, (
        f"the tool was started anyway, on whatever network the adapter picked: "
        f"{sent.status_code} {sent.text[:200]}"
    )
