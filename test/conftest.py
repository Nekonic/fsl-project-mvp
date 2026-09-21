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


@pytest.fixture(scope="session", autouse=True)
def terminal_leaves_by_the_front_door(stack_is_up):
    """Put the shell's origin back to the default before measuring anything.

    The console can point the terminal's traffic at another segment, and the
    proxy reads that choice from a file - so it survives the session that made
    it. A run that starts with the shell pointed at Hong Kong attributes every
    terminal case to an address on the wrong continent, and nothing says so.
    """
    requests.post(f"{PLATFORM_URL}/api/attacker/origin/", json={"origin": ""},
                  timeout=60)


@pytest.fixture(scope="session", autouse=True)
def defence_is_on(stack_is_up):
    """Refuse to measure a defence that is switched off.

    A suppression silences a rule for an hour, and one left behind - by a run
    that died, or by somebody clicking in the console - makes every later run
    measure a range with a hole in it. The symptom is not "a rule is off": it
    is "the probe raised no alert at all", which reads as a broken pipeline
    and sends the next session looking in the wrong place. It already did.
    """
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
    """Give the target back its unsolved objectives.

    The red team's cases take objectives now, so every acceptance run has to
    start from a target in a known state, or it measures whatever the last run
    left behind.

    There are two targets now. The wiki judges itself by its own access log,
    which survives everything, so a run that does not clear it starts with the
    inside already lost and scores the defence for a breach from last week.

    A restart is not enough and neither is --force-recreate; see DECISIONS.
    Afterwards the WAF must still reach it: nginx resolves its upstream once,
    at start, so a target that comes back on a different address leaves the
    whole range answering 502 - which would surface as a defence failure.
    """
    (REPO_ROOT / "deploy/wiki/logs/read.log").write_text("")

    subprocess.run(
        ["docker", "compose", "rm", "-sf", "juice-shop"],
        capture_output=True, timeout=120, check=True, cwd=REPO_ROOT,
    )
    subprocess.run(
        ["docker", "compose", "up", "-d", "juice-shop"],
        capture_output=True, timeout=300, check=True, cwd=REPO_ROOT,
    )

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
        "  docker compose up -d --force-recreate waf suricata"
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


def from_attacker(path: str) -> None:
    """Send one request from the attacker's box, the way the terminal would.

    Goes out through the stamping proxy because that is how the container is
    configured, so it carries a marker whenever a label is open. Dialled by
    the site's own name, which is what a person at that prompt types.
    """
    result = subprocess.run(
        [
            "docker", "exec", "fsl-kali", "curl", "-s", "-o", "/dev/null",
            "--max-time", "20", f"http://shop.com{path}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"could not reach the target from the attacker box: {result.stderr}"
    )


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

    # A session that ingested nothing says nothing about the defence. Report it
    # as what it is - the pipeline delivered no data - so that a cold stack, a
    # stalled Filebeat or a corrupt log never reads as "the attack got through".
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
    """Wait until both engines have landed, not just the first one.

    Suricata alerts reach Elasticsearch before ModSecurity's audit log does, so
    stopping at the first true positive leaves half the detections missing and
    every downstream assertion racing the pipeline.
    """

    def ready(totals):
        if totals["tp"] <= 0:
            return False
        detections = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
        ).json()
        return {d["source"] for d in detections} == {"suricata", "modsecurity"}

    return score_when_ready(session_id, until=ready)
