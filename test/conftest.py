import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

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
    """Fail rather than skip when the stack is down.

    An acceptance check that quietly skips reads as "passed".
    """
    for url in (PLATFORM_URL, TARGET_URL):
        assert _reachable(url), (
            f"could not reach {url}. Run `docker compose up -d --build` first."
        )


def run_redteam() -> int:
    """Run the red team once and return the session number."""
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


def score_when_ready(session_id: int, until, timeout: float = 150.0) -> dict:
    """Re-ingest and re-score until the logs have reached Elasticsearch.

    Filebeat to Elasticsearch is asynchronous, so the first ingest can be empty.
    Retries until `until` holds or the time runs out.
    """
    deadline = time.time() + timeout
    last: dict = {}

    while time.time() < deadline:
        ingest = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/")
        if ingest.ok:
            last = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/").json()
            if until(last):
                return last
        time.sleep(5)

    assert last, "never got a score back. Check Elasticsearch and Filebeat."
    return last


@pytest.fixture(scope="session")
def session_id(stack_is_up):
    return run_redteam()


@pytest.fixture(scope="session")
def score(session_id):
    return score_when_ready(session_id, until=lambda s: s["tp"] > 0)
