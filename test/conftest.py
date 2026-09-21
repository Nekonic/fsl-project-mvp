import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from range import ATTACKER, GATEWAY, SENSOR, TARGET, recreate, run, start_hint

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_URL = "http://localhost:8000"
TARGET_URL = "http://localhost:8080"

SESSION_LINE = re.compile(r"^session (\d+) done$")

def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False

@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    for url in (PLATFORM_URL, TARGET_URL):
        assert _reachable(url), (
            f"could not reach {url}. Run `{start_hint()}` first."
        )

@pytest.fixture(scope="session", autouse=True)
def terminal_leaves_by_the_front_door(stack_is_up):
    requests.post(f"{PLATFORM_URL}/api/attacker/origin/", json={"origin": ""},
                  timeout=60)

@pytest.fixture(scope="session", autouse=True)
def defence_is_on(stack_is_up):
    active = requests.get(f"{PLATFORM_URL}/api/rules/suppressions/", timeout=60)
    if not active.ok:
        return
    silenced = [s["sid"] for s in active.json()["suppressions"]]
    assert not silenced, (
        f"sid {silenced} are suppressed, so this run would score a defence "
        f"with a hole in it. Restore them first: "
        f"POST /api/rules/suppressions/<id>/restore/"
    )

def reset_target() -> None:
    record = REPO_ROOT / "deploy/wiki/logs/read.log"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("")

    recreate(TARGET)

    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            if requests.get(TARGET_URL, timeout=5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(3)

    raise AssertionError(
        f"the target was reset but {TARGET_URL} does not answer through the "
        "WAF. nginx caches its upstream address at start, so recreate it too:\n"
        f"  {start_hint(GATEWAY, SENSOR, fresh=True)}"
    )

def run_redteam() -> int:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "redteam" / "run.py")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"red team run failed:\n{result.stdout}\n{result.stderr}"
    )

    for line in result.stdout.splitlines():
        found = SESSION_LINE.match(line.strip())
        if found:
            return int(found.group(1))
    raise AssertionError(f"no session number in output:\n{result.stdout}")

def from_attacker(path: str) -> None:
    result = run(
        ATTACKER,
        ["curl", "-s", "-o", "/dev/null", "--max-time", "20",
         f"http://shop.com{path}"],
    )
    assert result.ok, (
        f"could not reach the target from the attacker box: {result.stderr}"
    )

def score_when_ready(session_id: int, until, timeout: float = 150.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}

    while time.time() < deadline:
        ingest = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/")
        if ingest.ok:
            last = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/").json()
            if until(last):
                return last
        time.sleep(5)

                                                                               
                                                                              
                                                                                
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()
    assert detections, (
        f"session {session_id} ingested no detections at all in {timeout:.0f}s, "
        f"so nothing was scored and nothing can be concluded about the defence. "
        f"This is a pipeline failure, not a detection failure: check Filebeat "
        f"and Elasticsearch. A stack that restarted recently needs a few "
        f"minutes before new events reach the index."
    )
    assert last, "never got a score back. Check Elasticsearch and Filebeat."
    return last

@pytest.fixture(scope="session")
def session_id(stack_is_up):
    reset_target()
    return run_redteam()

@pytest.fixture(scope="session")
def score(session_id):

    def ready(totals):
        if totals["tp"] <= 0:
            return False
        detections = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
        ).json()
        return {d["source"] for d in detections} == {"suricata", "modsecurity"}

    return score_when_ready(session_id, until=ready)
