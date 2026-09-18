import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_URL = "http://localhost:8000"
TARGET_URL = "http://localhost:8080"


def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False


@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    """스택이 떠 있지 않으면 건너뛰지 않고 실패한다.

    완료 기준 검증이 조용히 skip 되면 "통과"로 오독된다.
    """
    for url in (PLATFORM_URL, TARGET_URL):
        assert _reachable(url), (
            f"{url} 에 닿지 못했다. `docker compose up -d --build` 를 먼저 실행하라."
        )


def run_redteam() -> int:
    """레드팀을 한 판 돌리고 세션 번호를 돌려준다."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "redteam" / "run.py")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"레드팀 실행 실패:\n{result.stdout}\n{result.stderr}"

    for line in result.stdout.splitlines():
        if line.startswith("세션 ") and "완료" in line:
            return int(line.split()[1])
    raise AssertionError(f"세션 번호를 찾지 못했다:\n{result.stdout}")


def score_when_ready(session_id: int, until, timeout: float = 150.0) -> dict:
    """로그가 ES 에 도달할 때까지 기다리며 반복 수집·채점한다.

    Filebeat -> Elasticsearch 는 비동기라 첫 수집이 비어 있을 수 있다.
    `until` 이 참이 되거나 시간이 다 될 때까지 다시 시도한다.
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

    assert last, "채점 결과를 한 번도 받지 못했다. Elasticsearch/Filebeat 를 확인하라."
    return last


@pytest.fixture(scope="session")
def session_id(stack_is_up):
    return run_redteam()


@pytest.fixture(scope="session")
def score(session_id):
    return score_when_ready(session_id, until=lambda s: s["tp"] > 0)
