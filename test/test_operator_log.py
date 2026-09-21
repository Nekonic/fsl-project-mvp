import uuid

import pytest
import requests

from conftest import PLATFORM_URL
from range import ATTACKER, run

def typed(command):
    shell = f"printf '{command}\\nexit\\n' | bash -i"
    return run(ATTACKER, ["bash", "-c", shell], timeout=120)

@pytest.fixture(scope="module")
def recorded(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    marker = str(uuid.uuid4())

    requests.post(
        f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": marker}, timeout=60
    )
    typed(f"nmap --version")
    requests.post(
        f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": None}, timeout=60
    )
    typed("echo after")

    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/commands/", timeout=120
    )
    assert listed.status_code == 200, listed.text
    return marker, listed.json()["commands"]

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
