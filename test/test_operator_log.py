import pytest

@pytest.fixture(scope="module")
def recorded(terminal_session):
    listed = terminal_session["commands"]
    assert listed.status_code == 200, listed.text
    return terminal_session["marker"], listed.json()["commands"]

def test_what_was_typed_at_the_terminal_comes_back(recorded):
    _, commands = recorded

    assert [c["text"] for c in commands][-2:] == ["nmap --version", "echo after"], (
        "the proxy sees HTTP requests and nothing sees nmap, so a window case "
        "said an attack happened without saying what it was"
    )

def test_a_command_typed_while_a_case_was_open_is_attributed_to_it(recorded):
    marker, commands = recorded

    attributed = {c["text"]: c["case_id"] for c in commands}

    assert attributed["nmap --version"] == marker
    assert attributed["echo after"] == "", (
        "everything typed after the case closed was still filed under it"
    )
