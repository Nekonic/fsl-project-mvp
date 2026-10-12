import os
import re
import time
from pathlib import Path

import pytest
import requests

import range as the_range
from opening import CAP_REFUSAL, has_room, refused_for_room, retried, wait_for_room
from range import ATTACKER, RangeUnavailable, SCORER, ThroughPlatform, run, start_hint, substrate, use

pytest_plugins = ["shared_sessions"]

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_URL = os.environ.get("FSL_PLATFORM_URL", "http://localhost:8000").rstrip("/")
PLATFORM_FROM_SCORER = "http://localhost:8000"
TARGET_PUBLIC = "http://board.com"

SESSION_LINE = re.compile(r"^session (\d+) done$")
OPENED_LINE = re.compile(r"^session (\d+) opened$")
CLOSING = re.compile(re.escape(PLATFORM_URL) + r"/api/sessions/(\d+)/close/?")

ENGINES = {"suricata", "modsecurity"}

SPLIT = os.environ.get("FSL_SPLIT", "")
IDLE = SPLIT == "idle"
BESIDE_ANOTHER_WORKER = SPLIT == "worker" and int(os.environ.get("FSL_WORKERS") or 1) > 1
REDTEAM_ATTEMPTS = 3

COMPOSE_RANGE_ONLY = {
    "test_attacker_box", "test_board_exfil", "test_concurrent_sessions",
    "test_event_time",
    "test_fabric", "test_front_door", "test_judge_isolation", "test_lesson",
    "test_operator_log", "test_ready", "test_segmentation",
    "test_strategy_comparison", "test_terminal", "test_topology",
    "test_window_correlation",
}

def range_readiness() -> dict | None:
    try:
        readiness = requests.get(f"{PLATFORM_URL}/api/range/ready/", timeout=30).json()
    except (requests.RequestException, ValueError):
        return None
    return readiness if isinstance(readiness, dict) else None

RESET_WAIT = 1800
RESET_POLL = 2
SETTLING = {"RESETTING", "REBUILDING", "CHECKING"}
RESETTING = {"RESETTING", "REBUILDING"}

def settled(readiness: dict | None) -> bool:
    if readiness is None:
        return False
    return bool(readiness.get("ready", True)) or (readiness.get("slot") or {}).get("phase") not in SETTLING

def wait_out_a_reset() -> dict | None:
    deadline = time.monotonic() + RESET_WAIT
    while True:
        readiness = range_readiness()
        if settled(readiness) or time.monotonic() >= deadline:
            return readiness
        time.sleep(RESET_POLL)

def range_substrate() -> str:
    return (range_readiness() or {}).get("substrate") or "compose"

def pytest_collection_modifyitems(config, items):
    substrate = range_substrate()
    use(substrate)
    if substrate == "compose":
        return
    skip = pytest.mark.skip(
        reason=f"exercises the compose range; the scored range here is {substrate}"
    )
    for item in items:
        if item.module.__name__ in COMPOSE_RANGE_ONLY:
            item.add_marker(skip)

def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False

def target_code(path: str = "/", session: int | None = None) -> int:
    probe = run(
        ATTACKER,
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
         f"{TARGET_PUBLIC}{path}"],
        session=session,
    )
    code = probe.stdout.strip()
    return int(code) if code.isdigit() else 0

def target_answers() -> bool:
    try:
        return 0 < target_code() < 500
    except RangeUnavailable:
        return False

@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    assert _reachable(PLATFORM_URL), (
        f"could not reach {PLATFORM_URL}. Run `{start_hint()}` first."
    )
    if IDLE:
        return
    readiness = wait_out_a_reset()
    assert readiness is not None, (
        f"{PLATFORM_URL}/api/range/ready/ gave no readable answer within {RESET_WAIT}s"
    )
    if (readiness.get("substrate") or "compose") != "compose":
        assert readiness.get("ready"), f"the range is not ready: {readiness}"
        return
    if SPLIT:
        return
    assert target_answers(), (
        f"the target does not answer through the WAF from inside the range. "
        f"Run `{start_hint()}` first."
    )

MADE_BY_THIS_RUN: set[int] = set()
OPENED_IN_ORDER: list[int] = []
OPEN_NOW: set[int] = set()

def listed_for_pruning(session_id: int) -> int:
    MADE_BY_THIS_RUN.add(session_id)
    listed = os.environ.get("FSL_ACCEPTANCE_SESSIONS")
    if listed:
        with open(listed, "a", encoding="utf-8") as ids:
            ids.write(f"{session_id}\n")
    return session_id

def made_by_this_run(session_id: int) -> int:
    if session_id not in MADE_BY_THIS_RUN:
        OPENED_IN_ORDER.append(session_id)
    return listed_for_pruning(session_id)

def open_sessions() -> int | None:
    try:
        return len(requests.get(f"{PLATFORM_URL}/api/sessions/?state=open", timeout=30).json())
    except (requests.RequestException, ValueError, TypeError):
        return None

def room_on_the_range() -> bool:
    counted = open_sessions()
    return counted is not None and has_room(range_readiness(), counted)

def wait_for_room_on_the_range() -> bool:
    return wait_for_room(room_on_the_range, RESET_WAIT, RESET_POLL)

def room_after_a_pause() -> bool:
    time.sleep(RESET_POLL)
    return wait_for_room_on_the_range()

def opened_when_there_is_room(post, url, *args, **kwargs):
    return retried(
        lambda: post(url, *args, **kwargs),
        lambda answer: refused_for_room(answer.status_code, answer.text),
        room_after_a_pause,
        attempts=int(RESET_WAIT / RESET_POLL),
    )

class Standing:
    def __init__(self):
        self.session = None

    def id(self) -> int | None:
        if not BESIDE_ANOTHER_WORKER or substrate() != "compose":
            return None
        assert not OPEN_NOW, (
            f"a range call named no session while session {sorted(OPEN_NOW)} is "
            f"open; beside another worker the newest stack is not this test's, so "
            f"pass session= explicitly"
        )
        if self.session is None:
            opened = opened_when_there_is_room(
                REAL_POST, f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600
            )
            assert opened.status_code == 201, (
                f"could not open a session for the checks that need a standing "
                f"stack: {opened.text}"
            )
            self.session = listed_for_pruning(opened.json()["id"])
        return self.session

    def release(self) -> None:
        if self.session is not None:
            REAL_POST(f"{PLATFORM_URL}/api/sessions/{self.session}/close/", json={}, timeout=120)
            self.session = None

REAL_POST = requests.post
STANDING = Standing()
if BESIDE_ANOTHER_WORKER:
    the_range.default_to(STANDING.id)

@pytest.fixture
def standing_stack(stack_is_up):
    return STANDING.id()

@pytest.fixture(scope="session", autouse=True)
def the_run_leaves_no_session_open(stack_is_up):
    real_post = requests.post

    def post(url, *args, **kwargs):
        opening = url.rstrip("/") == f"{PLATFORM_URL}/api/sessions"
        if not opening:
            answer = real_post(url, *args, **kwargs)
            closed = CLOSING.fullmatch(url)
            if closed and answer.status_code in (200, 409):
                OPEN_NOW.discard(int(closed.group(1)))
            return answer
        STANDING.release()
        answer = opened_when_there_is_room(real_post, url, *args, **kwargs)
        if answer.status_code == 201:
            OPEN_NOW.add(made_by_this_run(answer.json()["id"]))
        return answer

    requests.post = post
    try:
        yield
    finally:
        requests.post = real_post
        STANDING.release()
        for session_id in sorted(MADE_BY_THIS_RUN):
            real_post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)

def _close_opened_since(count: int) -> None:
    for session_id in OPENED_IN_ORDER[count:]:
        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)

@pytest.fixture(scope="module", autouse=True)
def a_module_closes_the_sessions_it_opened(the_run_leaves_no_session_open):
    count = len(OPENED_IN_ORDER)
    yield
    _close_opened_since(count)

def resetting(readiness: dict | None) -> bool:
    slot = (readiness or {}).get("slot") or {}
    return slot.get("phase") in RESETTING or (slot.get("reset") or {}).get("state") == "running"

def wait_out_a_running_reset() -> dict | None:
    deadline = time.monotonic() + RESET_WAIT
    while True:
        readiness = range_readiness()
        if not resetting(readiness) or time.monotonic() >= deadline:
            return readiness
        time.sleep(RESET_POLL)

@pytest.fixture(autouse=True)
def the_range_is_not_resetting(stack_is_up):
    if substrate() == ThroughPlatform.substrate and not IDLE:
        readiness = wait_out_a_running_reset()
        assert not resetting(readiness), (
            f"the range was still resetting after {RESET_WAIT}s: {readiness}. A "
            f"closed session rebuilds every slot VM, and a test that reaches a "
            f"host meanwhile finds it gone"
        )

@pytest.fixture(autouse=True)
def a_test_closes_the_sessions_it_opened(the_run_leaves_no_session_open):
    count = len(OPENED_IN_ORDER)
    yield
    _close_opened_since(count)

def nothing_is_open(answer) -> bool:
    return answer.status_code == 409 and "no session is open" in answer.text

@pytest.fixture(scope="session", autouse=True)
def terminal_leaves_by_the_front_door(stack_is_up):
    if SPLIT:
        return
    requests.post(f"{PLATFORM_URL}/api/attacker/origin/", json={"origin": ""},
                  timeout=60)

@pytest.fixture(scope="session", autouse=True)
def terminal_carries_no_case(stack_is_up):
    if SPLIT:
        return
    cleared = requests.post(
        f"{PLATFORM_URL}/api/attacker/label/", json={"case_id": ""}, timeout=60
    )
    assert cleared.ok or nothing_is_open(cleared), (
        f"could not clear the terminal's case label: {cleared.text}. A label "
        f"left behind by an earlier run stamps every request from the terminal "
        f"with a case that is not in this run."
    )

@pytest.fixture(scope="session")
def baseline_rules(stack_is_up):
    committed = (REPO_ROOT / "deploy/suricata/rules/local.rules").read_text()
    fresh = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600).json()["id"]
    live = requests.get(
        f"{PLATFORM_URL}/api/rules/", params={"session": fresh}, timeout=60
    ).json()["content"]
    requests.post(f"{PLATFORM_URL}/api/sessions/{fresh}/close/", json={}, timeout=120)

    assert live == committed, (
        "the sensor is not running the rule set this repo declares. A test "
        "that captures 'whatever was there' and restores it would cement "
        "somebody else's leftovers as the baseline."
    )
    return committed

@pytest.fixture(scope="session", autouse=True)
def defence_is_on(stack_is_up):
    active = requests.get(f"{PLATFORM_URL}/api/rules/suppressions/", timeout=60)
    if not active.ok:
        return
    live = {row["id"] for row in requests.get(
        f"{PLATFORM_URL}/api/sessions/?state=open", timeout=30
    ).json()}
    silenced = [s["sid"] for s in active.json()["suppressions"]
                if s.get("session_id") is None or s["session_id"] not in live]
    assert not silenced, (
        f"sid {silenced} are suppressed, so this run would score a defence "
        f"with a hole in it. Restore them first: "
        f"POST /api/rules/suppressions/<id>/restore/"
    )

def _opened_by(output: str) -> None:
    for line in output.splitlines():
        found = OPENED_LINE.match(line.strip())
        if found:
            session_id = made_by_this_run(int(found.group(1)))
            requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120)

def _redteam_once():
    try:
        result = run(
            SCORER,
            ["python", "redteam/run.py",
             "--platform", PLATFORM_FROM_SCORER,
             "--tool-target", TARGET_PUBLIC],
            timeout=300,
        )
    except RangeUnavailable as exc:
        _opened_by(exc.output)
        raise
    _opened_by(result.stdout)
    return result

def _refused_a_session(result) -> bool:
    return not result.ok and CAP_REFUSAL in result.output and not any(
        OPENED_LINE.match(line.strip()) for line in result.stdout.splitlines()
    )

def run_redteam() -> int:
    STANDING.release()
    wait_out_a_reset()
    result = retried(_redteam_once, _refused_a_session, wait_for_room_on_the_range,
                     attempts=REDTEAM_ATTEMPTS)
    assert result.ok, f"red team run failed:\n{result.output}"

    for line in result.stdout.splitlines():
        found = SESSION_LINE.match(line.strip())
        if found:
            return made_by_this_run(int(found.group(1)))
    raise AssertionError(f"no session number in output:\n{result.output}")

def from_attacker(path: str, session: int | None = None) -> None:
    result = run(
        ATTACKER,
        ["curl", "-s", "-o", "/dev/null", "--max-time", "20",
         f"http://board.com{path}"],
        session=session,
    )
    assert result.ok, (
        f"could not reach the target from the attacker box: {result.stderr}"
    )

def score_when_ready(session_id: int, until, timeout: float = 150.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}

    while time.time() < deadline:
        ingest = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/", timeout=120)
        if ingest.ok:
            last = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/").json()
            if until(last):
                return last
        time.sleep(2)

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

def credited_to(session_id: int, totals: dict, **case) -> list[dict]:
    found = next(
        (c for c in totals["per_case"]
         if all(c[field] == value for field, value in case.items())),
        None,
    )
    if found is None:
        return []
    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    return [d for d in listed if d["detection_id"] in found["detection_ids"]]

def seen_by_both_engines(session_id: int, totals: dict, **case) -> bool:
    return ENGINES <= {d["source"] for d in credited_to(session_id, totals, **case)}
