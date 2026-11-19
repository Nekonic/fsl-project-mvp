import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from content import service as content
from tests import rounds
from testing import factories, fakerange
from testing.fakes import FakeElastic, Sensor

REPO = Path(__file__).resolve().parents[3]
RECORDED = {
    "board-sqli-search": {"method": "GET", "host": "board.com", "path": "/search/?q=%27+or+1%3D1--"},
    "board-sqli-login-bypass": {"method": "POST", "host": "board.com", "path": "/accounts/login/",
                                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                                "body": "username=admin%27--&password=x"},
    "board-normal-search": {"method": "GET", "host": "board.com", "path": "/search/?q=hello"},
    "board-normal-search-with-apostrophe": {"method": "GET", "host": "board.com", "path": "/search/?q=it%27s"},
    "board-normal-post-list": {"method": "GET", "host": "board.com", "path": "/"},
    "board-normal-sort": {"method": "GET", "host": "board.com", "path": "/?sort=title"},
    "board-normal-search-korean": {"method": "GET", "host": "board.com", "path": "/search/?q=%ED%95%9C"},
}
TOOL_RECORDED = ("board-sqli-orderby-sqlmap",)
PROBE_CASES = ("board-sqli-search", "board-sqli-login-bypass", "board-sqli-orderby-sqlmap")
SEARCH_RULE = 'alert http any any -> any any (msg:"SQL injection in search"; sid:1001; rev:1;)\n'
LOGIN_RULE = 'alert http any any -> any any (msg:"SQL login bypass"; sid:1002; rev:1;)\n'
BASELINE = "alert http any any -> any any (msg:\"baseline\"; sid:9000001; rev:1;)\n"
SECOND_SENSOR = {"node": "cr-infra", "container": "sensor2", "roles": ["sensor2"],
                 "rules": "/var/lib/suricata/rules/second.rules", "reload": "suricatasc -c reload-rules"}


def copied_source(into: Path) -> Path:
    for folder in sorted((REPO / "wargames").iterdir()):
        if (folder / "wargame.yaml").is_file():
            (into / "wargames" / folder.name).mkdir(parents=True)
            for name in ("wargame.yaml", "topology.yaml", "objectives.yaml", "traffic.yaml"):
                if (folder / name).is_file():
                    shutil.copy(folder / name, into / "wargames" / folder.name / name)
    shutil.copytree(REPO / "redteam" / "cases", into / "redteam" / "cases")
    (into / "platform" / "range").mkdir(parents=True)
    shutil.copy(REPO / "platform" / "range" / "declaration.yaml", into / "platform" / "range" / "declaration.yaml")
    shutil.copytree(REPO / "deploy" / "kibana", into / "deploy" / "kibana")
    return into


def recorded(source: Path) -> None:
    probes = source / "wargames" / "board" / "probes"
    probes.mkdir()
    cases = {**RECORDED, **{case: None for case in TOOL_RECORDED}}
    (probes / "manifest.json").write_text(json.dumps({
        "image_digest": "sha256:placeholder", "recorded_at": "2026-11-20T00:00:00+00:00",
        "cases": {case: {"marker": f"probe-{case}"} for case in cases}}))
    for case, request in cases.items():
        (probes / f"{case}.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + case.encode())
        if request is not None:
            (probes / f"{case}.request.json").write_text(json.dumps(request))
            (probes / f"{case}.response.json").write_text(json.dumps({"status": 200, "body": "ok"}))


def with_second_sensor(source: Path) -> None:
    for path in sorted(source.glob("wargames/*/topology.yaml")):
        document = yaml.safe_load(path.read_text())
        document["devices"]["cr-ids2"] = dict(SECOND_SENSOR)
        document["watches"]["sensor2"] = "gateway"
        path.write_text(yaml.safe_dump(document, sort_keys=False))


@pytest.fixture
def source(tmp_path, settings, monkeypatch):
    made = copied_source(tmp_path / "source")
    recorded(made)
    settings.CR_SOURCE = made
    monkeypatch.setenv("CR_SUBSTRATE", "testing.fakerange.connect")
    monkeypatch.setenv("CR_JUMP_DIR", str(tmp_path / "jump"))
    monkeypatch.setenv("CR_JUMP_HOST", "jump.range.test")
    return made


@pytest.fixture
def cyber_range():
    made = fakerange.DefenceRange()
    made.runner("sensor").rules = BASELINE
    made.node_runner("sensor").fires = {
        "board-sqli-search": {"1001": "SQL injection in search"},
        "board-normal-search-with-apostrophe": {"1001": "SQL injection in search"},
        "board-sqli-login-bypass": {"1002": "SQL login bypass"},
        "board-sqli-orderby-sqlmap": {"1001": "SQL injection in search"},
    }
    fakerange.HELD["range"] = made
    yield made
    fakerange.HELD.clear()


@pytest.fixture
def two_sensors(source, cyber_range):
    with_second_sensor(source)
    cyber_range.sensors["sensor2"] = Sensor(rules=BASELINE, path=SECOND_SENSOR["rules"])
    return cyber_range


@pytest.fixture
def board_round(db, source, cyber_range, learner):
    problem = content.save_document(factories.round_problem(objectives=["board-auth-user-admin"],
                                                            probe_cases=list(PROBE_CASES)))
    return rounds.opened(problem, opened_by=learner)


@pytest.fixture
def defender(board_round, learner):
    return rounds.seated(board_round, "defence", user=learner)


@pytest.fixture
def as_defender(browser, defender, learner):
    browser.force_authenticate(learner)
    return browser


@pytest.fixture
def es():
    found = FakeElastic()
    with patch("ingest.elastic.requests.post", found.post):
        yield found


@pytest.fixture
def at():
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=5)
