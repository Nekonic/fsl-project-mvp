from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

import lesson
import wargames
from api.models import Case, Detection, Session
from range.ports import Ran
from rules import crs
from tests.test_lesson_api import HELD, TRUTH, Stand
from tests.test_scenario_discovery import A_SCENARIO
from tests.test_strings import tables

pytestmark = pytest.mark.django_db

KOREAN = "\uc11c\uc6b8 \ub9db\uc9d1 \ucd94\ucc9c"
SQLMAP = ("board-sqli-orderby-sqlmap", "board-sqli-orderby-sqlmap-tamper")
QUICK = override_settings(LESSON_ALERT_WAIT=0, LESSON_ALERT_POLL=0)

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

def test_the_board_offers_the_course_in_order_and_guidance_alone_still_opens_the_exclusion_lesson(client):
    fire, _ = sensed({})
    with patch("api.views.harness.fire", fire):
        guided = client.post_json("/api/sessions/", {"guidance": True}).json()

    assert [found["id"] for found in wargames.lessons("board")][:3] == ["console-tour", "read-the-block", "waf-exclusion"]
    assert guided["lesson_id"] == "waf-exclusion", "default_lesson keeps the call that predates the list"

def test_a_default_lesson_the_scenario_does_not_declare_is_refused(settings, tmp_path):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    lessons = [{"id": "a", "order": 1, "text": "lesson.demo", "cases": ["board-normal-search"]}]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": lessons, "default_lesson": "b"}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match="default_lesson"):
        wargames._discover()

@pytest.mark.parametrize("fields, check, reason", [
    ({}, {"kind": "answer", "of": "status", "path": "x"}, "read from the record"),
    ({}, {"kind": "answer", "of": "rule"}, "read from the record"),
    ({}, {"kind": "answer"}, "accept list"),
    ({}, {"kind": "detect", "case": "board-normal-search", "expect": "alert"}, "detected_by"),
    ({"detected_by": "suricata"}, {"kind": "detect", "case": "board-normal-search", "expect": "loud"}, "detect step"),
    ({}, {"kind": "rules"}, "detected_by"),
    ({}, {"kind": "level"}, "solved_at"),
    ({"mode": "lazy"}, {"kind": "click"}, "mode"),
    ({"controls": ["kibana"]}, {"kind": "click"}, "controls"),
    ({"detected_by": "modsecurity"}, {"kind": "click"}, "detected_by"),
    ({"solved_at": {"paranoia": 9}}, {"kind": "click"}, "solved_at"),
])
def test_a_lesson_that_could_not_be_judged_is_refused_at_discovery(settings, tmp_path, fields, check, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    lessons = [{"id": "a", "order": 1, "text": "lesson.demo", "cases": ["board-normal-search"],
                "steps": [{"id": "one", "check": check}], **fields}]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "lessons": lessons}))
    settings.FSL_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

def test_every_lesson_has_its_words_in_both_languages():
    table = tables()
    for found in wargames.lessons("board"):
        prefix = found["text"]
        keys = [f"{prefix}.{part}" for part in ("title", "summary", "read", "write", "replay", "verify")]
        for card in found.get("theory") or []:
            keys += [f"{prefix}.theory.{card['id']}.title", f"{prefix}.theory.{card['id']}.body"]
        for hint in found.get("hints") or []:
            keys += [f"{prefix}.hint.{hint}.title", f"{prefix}.hint.{hint}.body"]
        for shown in found.get("steps") or []:
            keys += [f"{prefix}.{part}.{shown['id']}" for part in ("label", "coach", "nudge", "answer", "ok", "line")]
            check = shown["check"]
            keys += [f"{prefix}.option.{shown['id']}.{option}" for option in check.get("options", [])]
            keys += [f"{prefix}.wrong.{shown['id']}.{known}" for known in check.get("known", [])]
            if check["kind"] in ("alert", "level", "rules", "verify"):
                keys.append(f"{prefix}.fail.{shown['id']}")
            if shown.get("query"):
                keys.append(f"{prefix}.chip.{shown['id']}")
        for language in ("en", "ko"):
            missing = [key for key in keys if key not in table[language]]
            assert not missing, (found["id"], language, missing)

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
    session = taught("console-tour")
    blocked(session, "other", "a-seed-case", "/search/?q=%27+OR+1%3D1--", "942100")
    with quietly():
        nothing = step(client, session, "rule", body={"answer": "942100"}).json()
        blocked(session, "mine:0", session.browse_marker, "/search/?q=%27+OR+1%3D1--", "942100")
        blocked(session, "mine:1", session.browse_marker, "/search/?q=%27+OR+1%3D1--", "949110")
        total = step(client, session, "rule", body={"answer": "949110"}).json()
        right = step(client, session, "rule", body={"answer": "942100"}).json()

    assert (nothing["passed"], nothing["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert total["reason"] == ["lesson.tour.wrong.rule.949110", []]
    assert right["passed"] is True

def test_the_parameter_is_read_from_the_record_of_the_block_not_from_an_answer_key(client):
    session = taught("read-the-block")
    blocked(session, "seed:0", "a-seed-case", "/search/?q=O%27Brien", "920273",
            match="Matched \"Operator `ValidateByteRange' with parameter `38,44-46' against variable `ARGS:q' "
                  "(Value: `O'Brien' )")
    blocked(session, "seed:1", "a-seed-case", "/search/?q=O%27Brien", "949110", data="Total Score: 5")
    with quietly():
        wrong = step(client, session, "target", body={"answer": "REQUEST_URI"}).json()
        right = step(client, session, "target", body={"answer": "args:q"}).json()
        rule = step(client, session, "rule", "do/").json()

    assert wrong["passed"] is False
    assert right["passed"] is True, "a variable name is compared without case"
    assert rule["passed"] is True and rule["progress"]["rule"]["done_for_me"]
    shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert next(found for found in shown if found["id"] == "target")["check"] == {"kind": "answer"}

def test_a_variable_is_named_by_any_of_the_three_ways_modsecurity_writes_it():
    assert lesson.variable({"match": "Matched \"Operator `Rx' with parameter `x' against variable `ARGS:q' (Value: `x' )"}) == "ARGS:q"
    assert lesson.variable({"data": "Matched Data: ' found within ARGS:q: O'Brien"}) == "ARGS:q"
    assert lesson.variable({"data": "ARGS:q=O'Brien"}) == "ARGS:q"
    assert lesson.read_from("rule", [{"details": {"ruleId": "949110"}}, {"details": {"ruleId": "980170"}}]) == []

def test_a_lesson_judged_by_its_steps_refuses_verify_and_says_so_in_its_payload(client):
    session = taught("console-tour")

    assert client.post_json(f"/api/sessions/{session.pk}/verify/").status_code == 400
    assert client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["verifies"] is False

def test_the_assessment_opens_without_guidance_and_with_no_steps(client):
    fire, _ = sensed({})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"lesson": "assessment"}).json()

    shown = client.get(f"/api/sessions/{opened['id']}/").json()
    assert (opened["mode"], opened["defense"], shown["lesson"]["steps"]) == ("self", "minimal", [])
    assert shown["lesson"]["verifies"] is True

def test_the_level_step_passes_only_on_a_lower_level_with_no_exclusion(client):
    session = taught("choose-the-level", waf={"paranoia": 4, "exclusions": []})
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 4, "exclusions": []})
        unchanged = step(client, session, "level").json()
        stand.files[(session.pk, "gateway")] = crs.rendered(
            {"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "ARGS:q", "path": ""}]})
        excluded = step(client, session, "level").json()
        stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 3, "exclusions": []})
        lowered = step(client, session, "level").json()

    assert unchanged["reason"] == ["lesson.level.fail.level.unchanged", []]
    assert excluded["reason"] == ["lesson.level.fail.level.excluded", []]
    assert lowered["passed"] is True

def test_do_it_for_me_on_the_level_step_puts_the_level_through_the_waf_api(client):
    session = taught("choose-the-level", waf={"paranoia": 4, "exclusions": []})
    stand = Stand()
    stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 4, "exclusions": []})
    with patch("range.docker.Docker.runner", stand.runner()):
        done = step(client, session, "level", "do/").json()

    assert done["passed"] is True
    assert Session.objects.get(pk=session.pk).waf["paranoia"] == 2

def test_choose_the_level_passes_verify_only_at_the_highest_level_that_serves_everything(client):
    session = taught("choose-the-level")
    stand = Stand()
    passed = {}
    for level in (1, 2):
        stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": level, "exclusions": []})
        fire, _ = sensed({})
        with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
            passed[level] = client.post_json(f"/api/sessions/{session.pk}/verify/").json()

    assert passed[1]["passed"] is False
    assert ["lesson.diag.level_low", [1]] in passed[1]["diagnosis"]
    assert passed[2]["passed"] is True
    assert "solved_at" not in client.get(f"/api/sessions/{session.pk}/").json()["lesson"], "the answer stays on the server"

def test_the_rules_step_passes_once_the_sensor_holds_a_rule_the_lesson_did_not_start_with(client):
    session = taught("ids-signature")
    posture = (Path(settings.FSL_SOURCE) / "deploy/suricata/rules/no-uri-sqli.rules").read_text()
    applied = []
    with patch("api.views._live_rules", return_value=posture):
        unchanged = step(client, session, "write").json()
    with patch("api.views._live_rules", return_value=posture + 'alert http any any -> any any (msg:"x"; sid:9000101;)\n'):
        added = step(client, session, "write").json()
    with patch("api.views._live_rules", return_value=posture), \
            patch("api.views._apply", lambda content, session=None: applied.append(content)), \
            patch("api.views.lesson.added_rules", return_value=[9000101]):
        done = step(client, session, "write", "do/").json()

    assert (unchanged["passed"], unchanged["reason"]) == (False, ["lesson.ids.fail.write", []])
    assert added["passed"] is True and added["added"] == [9000101]
    assert done["passed"] is True and "sid:9000101;" in applied[0] and applied[0].startswith(posture.rstrip())
    shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert all("rule" not in found for found in shown), "the answer rule stays on the server"

@QUICK
def test_a_detect_step_fires_its_case_and_judges_the_suricata_alert_it_drew(client):
    session = taught("ids-signature")
    with quietly():
        fire, fired = sensed({"board-sqli-orderby-sqlmap": ["FSL path traversal attempt"]})
        with patch("api.views.harness.fire", fire):
            wrong_reason = step(client, session, "stock").json()
        fire, _ = sensed({"board-sqli-orderby-sqlmap": ["FSL SQLi attempt - sort is not a column name"]})
        with patch("api.views.harness.fire", fire):
            caught = step(client, session, "stock").json()
        fire, _ = sensed({"board-normal-sort": ["FSL SQLi attempt - sort is not a column name"]})
        with patch("api.views.harness.fire", fire):
            noisy = step(client, session, "sort").json()

    assert fired == ["board-sqli-orderby-sqlmap"]
    assert wrong_reason["reason"] == ["lesson.check.uncorroborated", ["board-sqli-orderby-sqlmap", "SQL"]]
    assert caught["passed"] is True and caught["detected"]["verdict"] == "TP"
    assert noisy["reason"][0] == "lesson.check.alerted" and noisy["detected"]["verdict"] == "FP"
    assert all(case.meta.get("check") for case in Case.objects.all()), "a check's replay is marked"

@QUICK
def test_an_ids_lesson_verifies_on_detection_alone_and_never_on_the_waf(client):
    session = taught("ids-signature")
    rule = "FSL SQLi attempt - sort is not a column name"
    runs = {}
    for name, alerts in {
        "missed": {},
        "caught": {SQLMAP[0]: [rule], SQLMAP[1]: [rule]},
        "noisy": {SQLMAP[0]: [rule], SQLMAP[1]: [rule], "board-normal-sort": [rule]},
    }.items():
        fire, _ = sensed(alerts)
        with quietly(), patch("api.views.harness.fire", fire):
            runs[name] = client.post_json(f"/api/sessions/{session.pk}/verify/").json()
    Detection.objects.create(session=session, detection_id="waf", source="modsecurity", signature="SQL Injection",
                             timestamp=timezone.now(), marker=Case.objects.filter(name=SQLMAP[0]).first().case_id)

    assert runs["missed"]["passed"] is False
    assert ["lesson.diag.missed", [SQLMAP[0]]] in runs["missed"]["diagnosis"]
    assert runs["caught"]["passed"] is True
    assert runs["caught"]["diagnosis"] == [["lesson.diag.detected_ratio", [2, 2]]]
    assert {row["name"]: row["verdict"] for row in runs["caught"]["cases"]}[SQLMAP[0]] == "TP"
    assert runs["noisy"]["passed"] is False
    assert ["lesson.diag.alerted", ["board-normal-sort"]] in runs["noisy"]["diagnosis"]
    score = client.get(f"/api/sessions/{session.pk}/score/").json()
    assert score["tp"] == score["fp"] == 0 and score["breaches"] == [], (
        "the lesson's replays stay out of both scores and mark no objective")

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
