import pytest

@pytest.fixture(scope="module")
def fired(origins_session):
    sent = origins_session["tool"]
    assert sent.status_code == 201, sent.text
    return sent.json()

def test_a_case_that_runs_a_tool_gets_the_tool_run_from_the_origin_it_was_told_to(fired):
    assert fired["meta"]["tool"] == "sqlmap", (
        "nothing else in this suite starts a tool, so the whole path from the "
        "console to a throwaway host on an origin's network was unguarded"
    )
    assert fired["meta"]["origin"] == "hk"

def test_an_origin_the_range_does_not_have_is_refused(origins_session):
    sent = origins_session["refused"]

    assert sent.status_code == 404, (
        f"the tool was started anyway, on whatever network the adapter picked: "
        f"{sent.status_code} {sent.text[:200]}"
    )
