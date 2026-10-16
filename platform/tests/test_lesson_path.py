import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote_plus

import pytest
import yaml
from django.conf import settings
from django.utils import timezone

import lesson
import wargames
from api.models import Detection, Session
from range.ports import Ran
from tests.test_lesson_api import HELD, TRUTH
from tests.test_scenario_discovery import A_SCENARIO

pytestmark = pytest.mark.django_db

KOREAN = "서울 맛집 추천"

def taught(lesson_id, **fields):
    defense = wargames.lesson_defense("board", lesson_id)
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), guidance=True, lesson=lesson_id,
                                  defense=defense, **fields)

def step(client, session, step_id, tail="check/", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def blocked(session, detection_id, marker, uri, rule, **details):
    Detection.objects.create(session=session, detection_id=detection_id, source="modsecurity", signature=rule,
                             timestamp=timezone.now(), marker=marker,
                             raw={"request": {"method": "GET", "uri": uri}, "details": {"ruleId": rule, **details}})

def sensed(alerts):
    fired = []

    def fire(case, launch, target_url):
        fired.append(case["name"])
        for position, signature in enumerate(alerts.get(case["name"], [])):
            Detection.objects.create(session=Session.objects.latest("id"), detection_id=f"{case['case_id']}:{position}",
                                     source="suricata", signature=signature, timestamp=timezone.now(),
                                     marker=case["case_id"])
        return SimpleNamespace(exit_code=0, output=HELD if case.get("tool") else "http_code=200\n")

    return fire, fired

def quietly():
    return patch("api.views._ingest", lambda session, within=None: {})

@pytest.mark.parametrize("fields, check, reason", [
    ({}, {"kind": "answer", "of": "status", "path": "x"}, "read from the record"),
    ({}, {"kind": "answer", "of": "rule"}, "read from the record"),
    ({}, {"kind": "answer"}, "accept list"),
    ({}, {"kind": "rules"}, "detected_by"),
    ({"detected_by": "modsecurity"}, {"kind": "click"}, "detected_by"),
    ({}, {"kind": "detect", "case": "board-normal-search", "expect": "alert"}, "kind is one of"),
    ({}, {"kind": "level"}, "kind is one of"),
])
def test_a_foundation_step_with_a_removed_kind_or_no_way_to_judge_it_is_refused_at_discovery(
        settings, tmp_path, fields, check, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    units = [{"id": "a", "order": 1, "text": "lesson.demo", "cases": ["board-normal-search"],
              "steps": [{"id": "one", "check": check}], **fields}]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": units}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

def test_the_new_benign_cases_are_ordinary_requests_and_the_comment_has_the_xss_comment_s_shape():
    korean = wargames.find_case("board", "board-normal-search-korean")
    comment = wargames.find_case("board", "board-normal-comment")
    xss = wargames.find_case("board", "board-xss-img-onerror-in-comment")

    assert not korean["malicious"] and korean["request"]["params"] == {"q": KOREAN}
    assert not comment["malicious"]
    assert {key: value for key, value in comment["request"].items() if key != "json"} == \
        {key: value for key, value in xss["request"].items() if key != "json"}
    assert set(comment["request"]["json"]) == set(xss["request"]["json"])

def test_the_rule_is_read_from_the_learner_s_own_blocked_request_and_the_total_is_explained(client):
    session = taught("f5")
    blocked(session, "other", "a-seed-case", "/search/?q=%27+OR+1%3D1--", "942100")
    with quietly():
        nothing = step(client, session, "rule", body={"answer": "942100"}).json()
        blocked(session, "mine:0", session.browse_marker, "/search/?q=%27+OR+1%3D1--", "942100")
        blocked(session, "mine:1", session.browse_marker, "/search/?q=%27+OR+1%3D1--", "949110")
        total = step(client, session, "rule", body={"answer": "949110"}).json()
        right = step(client, session, "rule", body={"answer": "942100"}).json()

    assert (nothing["passed"], nothing["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert total["reason"] == ["lesson.attack.wrong.rule.949110", []]
    assert right["passed"] is True

def test_the_parameter_is_read_from_the_record_of_the_request_not_from_an_answer_key(client):
    session = taught("f3")
    sent = {"id": 1, "at": time.time(), "method": "GET", "url": f"http://board.com/search/?q={quote_plus(KOREAN)}",
            "status": 200, "blocked": False, "ms": 40}
    with patch("api.site.kept", return_value=[sent]):
        wrong = step(client, session, "parameter", body={"answer": "REQUEST_URI"}).json()
        right = step(client, session, "parameter", body={"answer": "Q"}).json()
        path = step(client, session, "path", "do/").json()

    assert wrong["passed"] is False
    assert right["passed"] is True, "a parameter name is compared without case"
    assert path["passed"] is True and path["progress"]["path"]["done_for_me"]
    shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert next(found for found in shown if found["id"] == "parameter")["check"] == {"kind": "answer"}

def test_the_anomaly_totals_are_never_named_as_the_rule_that_matched():
    assert lesson.rules_named([{"details": {"ruleId": "949110"}}, {"details": {"ruleId": "980170"}}]) == []
    assert lesson.rules_named([{"details": {"ruleId": "942100"}}, {"details": {"ruleId": "949110"}}, {}]) == ["942100"]

def test_the_rules_step_passes_once_the_sensor_holds_a_rule_the_session_did_not_start_with(client):
    session = taught("3.1", course_scenario="3.1")
    ruleset = wargames.defense("board", session.defense)["suricata"]
    posture = (Path(settings.FSL_SOURCE) / "deploy/suricata/rules" / ruleset).read_text()
    applied = []
    with patch("api.views._live_rules", return_value=posture):
        unchanged = step(client, session, "fix").json()
    with patch("api.views._live_rules", return_value=posture + 'alert http any any -> any any (msg:"x"; sid:9000102;)\n'):
        added = step(client, session, "fix").json()
    with patch("api.views._live_rules", return_value=posture), \
            patch("api.views._apply", lambda content, session=None: applied.append(content)), \
            patch("api.views.lesson.added_rules", return_value=[9000102]):
        done = step(client, session, "fix", "do/").json()

    assert (unchanged["passed"], unchanged["reason"]) == (False, ["scenario.fixrule.fail.fix", []])
    assert added["passed"] is True and added["added"] == [9000102]
    assert done["passed"] is True and "sid:9000102;" in applied[0] and applied[0].startswith(posture.rstrip())
    shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert all("rule" not in found for found in shown), "the answer rule stays on the server"

def test_rule_validation_reports_suricata_s_error_lines_from_the_sensor_that_printed_them(client, settings):
    settings.FSL_EXTRA_SENSORS = (("estate-sensor", "/var/lib/suricata/rules/local.rules", ("reload",)),)
    quiet = "Info: conf-yaml-loader: Including configuration file conf.d/fsl.yaml.\n"
    loud = ("Info: suricata: This is Suricata version 7.0.8 RELEASE running in SYSTEM mode\n"
            "Error: detect-parse: unknown rule keyword 'contnet'.\n"
            "Error: detect: error parsing signature \"alert http any any -> any any (contnet:\\\"x\\\"; sid:1;)\" "
            "from file /dev/stdin at line 1\n")

    def runner(adapter, role, segment_id=""):
        return lambda argv, stdin=None, timeout=60.0: Ran(1, quiet if role == "sensor" else loud)

    with patch("range.docker.Docker.runner", runner):
        checked = client.post_json("/api/rules/validate/", {"content": "alert http any any -> any any (contnet:\"x\"; sid:1;)"})

    assert checked.status_code == 400
    assert checked.json()["errors"] == [
        "Error: detect-parse: unknown rule keyword 'contnet'.",
        "Error: detect: error parsing signature \"alert http any any -> any any (contnet:\\\"x\\\"; sid:1;)\" "
        "from file /dev/stdin at line 1",
    ]
    assert "contnet" in checked.json()["output"], "the output shown is the one that names the error"
