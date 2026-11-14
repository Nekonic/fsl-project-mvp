import ipaddress
import re
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from django.test import override_settings
from django.utils import timezone

import lesson
import wargames
from api import site
from api.models import Case, Detection, Objective, RuleSet, Session
from console import strings
from range import declared
from range.ports import Ran
from tests.test_gns3_maps import read_slot
from tests.test_lesson_api import DUMPED, TRUTH, WRITTEN, Stand, attacker, one_slot
from tests.test_scenario_discovery import A_SCENARIO
from tests.test_strings import tables

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "deploy" / "topology" / "range-openstack.gns3"
SQLMAP_AGENT = "sqlmap/1.8.4#stable (https://sqlmap.org)"
BOARD = "10.30.0.184"
WAF = "10.30.0.177"
CUSTOMER = "73.0.0.10"
KALI = "5.188.10.10"

def opened(lesson_id, **fields):
    defense = wargames.lesson_defense("board", lesson_id)
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), guidance=True, lesson=lesson_id,
                                  defense=defense, **fields)

def step(client, session, step_id, tail="check/", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def answer(client, session, step_id, given, query=WRITTEN, dev_request=1):
    return step(client, session, step_id, body={"answer": given, "query": query, "dev_request": dev_request}).json()

def browsed(url, status, request_id=1, ms=40, at=None):
    return {"id": request_id, "at": at or time.time(), "method": "GET", "url": f"http://board.com{url}",
            "status": status, "blocked": status == 403, "ms": ms}

def http_event(marker, url, status, host="cr-wargame-host", agent="Mozilla/5.0", event_type="http", **fields):
    headers = [{"name": "X-Request-ID", "value": marker}] if marker else []
    headers += [{"name": "X-Forwarded-For", "value": fields["xff"]}] if fields.get("xff") else []
    return {"event": {"module": "suricata"}, "event_type": event_type, "timestamp": (fields.get("at") or timezone.now()).isoformat(),
            "src_ip": fields.get("src_ip", WAF), "dest_ip": fields.get("dest_ip", BOARD),
            "dest_port": fields.get("dest_port", 8000), "log": {"syslog": {"hostname": host}},
            "http": {"url": url, "status": status, "http_method": "GET", "http_user_agent": agent,
                     "request_headers": headers}}

def waf_record(marker, uri):
    return {"event": {"module": "modsecurity"}, "@timestamp": timezone.now().isoformat(),
            "transaction": {"client_ip": CUSTOMER, "request": {"uri": uri, "headers": {"X-Request-ID": marker}},
                            "messages": []}}

def indexed(*events):
    return patch("api.views._fetched", lambda index, start, end, newest_first: (
        [(f"doc-{position}", event) for position, event in enumerate(events)], None))

def quietly():
    return patch("api.views._ingest", lambda session, within=None: {})

def on_map(found):
    return patch("api.views._map_found", lambda session: found)

def on_the_range():
    return override_settings(CR_TOPOLOGY=TOPOLOGY, RANGE=declared.read())

def detected(session, detection_id, source, marker, signature="", src_ip=None, **raw):
    return Detection.objects.create(session=session, detection_id=detection_id, source=source, signature=signature,
                                    timestamp=timezone.now(), marker=marker, src_ip=src_ip, raw=raw)

def passed(session, lesson_id, **steps):
    held = {step_id: {"reached": at.isoformat(), "passed": at.isoformat()} for step_id, at in steps.items()}
    Session.objects.filter(pk=session.pk).update(lesson_steps={lesson_id: held})
    session.refresh_from_db()

def kali_run(session, lesson_id, step_id, marker, **meta):
    steps = {**(session.lesson_steps.get(lesson_id) or {}),
             step_id: {"reached": (timezone.now() - timedelta(minutes=2)).isoformat(), "marker": marker}}
    Session.objects.filter(pk=session.pk).update(lesson_steps={**session.lesson_steps, lesson_id: steps})
    session.refresh_from_db()
    return Case.objects.create(session=session, case_id=marker, name="board-sqli-orderby-sqlmap-random-agent",
                               malicious=True, correlation="marker", started_at=timezone.now() - timedelta(minutes=1),
                               ended_at=timezone.now(), meta={"kali": step_id, "lesson": lesson_id, **meta})

def test_every_foundation_has_its_words():
    table = tables()
    for course in wargames.courses("board"):
        keys = [f"{course['text']}.{part}" for part in ("title", "brief", "done")]
        keys += [f"lesson.ref.{card}.title" for card in course.get("reference", [])]
        assert not [key for key in keys if key not in table], course["id"]
    for taught in wargames.foundations("board"):
        prefix, last = taught["text"], taught["steps"][-1]["id"]
        keys = [f"{prefix}.title"]
        keys += [f"lesson.ref.{card}.title" for card in taught.get("reference", [])]
        for shown in taught["steps"]:
            check, named = shown["check"], shown["id"]
            keys += [f"{prefix}.{part}.{named}" for part in ("title", "coach", "ok")]
            keys += [f"{prefix}.label.{named}"] if check["kind"] in ("answer", "choice") else []
            keys += [f"{prefix}.{part}.{named}" for part in ("nudge", "hint")] if named != last else []
            keys += [f"lesson.choice.{option}" for option in check.get("options", [])]
            keys += [f"{prefix}.wrong.{named}.{code}" for code in [*check.get("known", []),
                                                                  *(rule["says"] for rule in check.get("wrong_if", []))]]
            keys += [f"{prefix}.wrong.{named}.order"] if check.get("form") == "order" else []
            keys += [f"lesson.open.{shown['point']['opens']}"]
        assert not [key for key in keys if key not in table], taught["id"]

def test_the_six_foundations_are_two_courses_the_first_reading_the_range_and_the_second_changing_it():
    courses = {course["id"]: course for course in wargames.courses("board")}
    table = tables()

    assert [course["lessons"] for course in courses.values()] == [["f1", "f2", "f3"], ["f4", "f5", "f6"]]
    assert [table[f"{course['text']}.title"] for course in courses.values()] == ["로그 분석 기초", "공격 탐지 실습"]
    assert {wargames.lesson_defense("board", one) for one in courses["c1"]["lessons"]} == {"full"}
    assert not [step for one in courses["c1"]["lessons"] for step in wargames.lesson("board", lesson_id=one)["steps"]
                if step["check"]["kind"] in ("rules", "kali", "waf_changed", "replay", "loot")], "course 1 only reads"
    assert "kql" in courses["c1"]["reference"] and "kql" in courses["c2"]["reference"]

def test_a_kibana_step_rings_its_answer_only_once_the_learner_s_own_query_is_written():
    kibana = [step for taught in wargames.foundations("board") for step in taught["steps"]
              if (step["point"].get("kibana") or {}).get("doc") or (step["point"].get("kibana") or {}).get("sidebar")
              or (step["point"].get("kibana") or {}).get("hits")]

    assert kibana and all((step["point"]["kibana"]).get("kql") for step in kibana), [
        step["id"] for step in kibana if not step["point"]["kibana"].get("kql")]

def test_no_foundation_question_carries_a_fixed_answer():
    for taught in wargames.foundations("board"):
        for shown in taught["steps"]:
            check = shown["check"]
            if check["kind"] in ("answer", "choice"):
                assert "accept" not in check and check.get("of"), (taught["id"], shown["id"])

LOCATORS = {"panel", "map", "site", "dev", "kibana", "term"}

def test_every_step_opens_a_pane_points_at_one_element_and_the_last_is_solo_with_no_highlight(client):
    session = opened("f1")
    for taught in wargames.foundations("board"):
        *guided, last = taught["steps"]
        assert set(last["point"]) == {"opens"}, taught["id"]
        for shown in guided:
            point = shown["point"]
            assert "opens" in point and "pane" not in point, (taught["id"], shown["id"])
            assert len(LOCATORS & set(point)) == 1, (taught["id"], shown["id"])
            stage = point
            while stage.get("then"):
                assert stage.get("until") in ("sent", "applied"), (taught["id"], shown["id"])
                stage = stage["then"]
                assert len(LOCATORS & set(stage)) == 1 and set(stage) - LOCATORS <= {"until", "then"}
    Session.objects.filter(pk=session.pk).update(lesson="f6", defense="overbroad")
    steps = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert [one["solo"] for one in steps] == [False] * 7 + [True]

def test_the_map_questions_are_answered_from_the_addresses_and_captions_the_learner_s_map_shows(client):
    route = "customers > router > waf > board.com"
    session = opened("f1")
    with on_the_range(), on_map(read_slot()):
        given = {
            "kali_ip": [answer(client, session, "kali_ip", one)["passed"] for one in (KALI, CUSTOMER)],
            "board_ip": [answer(client, session, "board_ip", one)["passed"] for one in (BOARD, f"{BOARD}/24", WAF)],
            "dmz": [answer(client, session, "dmz", one)["passed"] for one in ("10.30.0.0/24", BOARD)],
            "log_host": [answer(client, session, "log_host", one)["passed"] for one in ("log-server", "waf")],
            "waf_ip": [answer(client, session, "waf_ip", one)["passed"] for one in (WAF, BOARD)],
        }
        reordered = answer(client, session, "path", " > ".join(reversed(route.split(" > "))))
        from_kali = answer(client, session, "path", "kali > router > waf > board.com")
        right = answer(client, session, "path", route)
        shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert given == {"kali_ip": [True, False], "board_ip": [True, True, False], "dmz": [True, False],
                     "log_host": [True, False], "waf_ip": [True, False]}
    assert reordered["reason"] == ["lesson.map.wrong.path.order", []], "right hosts in the wrong order say so"
    assert from_kali["passed"] is False and right["passed"] is True
    assert set(route.split(" > ")) <= set(shown["path"]["check"]["options"]) and "sw1" not in shown["path"]["check"]["options"]
    assert shown["dmz"]["point"]["map"] == {"zone": "sw1"}

def test_the_reference_s_address_table_lists_the_addresses_the_learner_s_map_draws(client):
    session = opened("f3")
    with on_the_range(), on_map(read_slot()):
        listed = client.get(f"/api/sessions/{session.pk}/lesson/addresses/").json()["addresses"]

    rows = {(one["host"], one["zone"], one["address"]) for one in listed}
    assert {("kali", "인터넷", KALI), ("waf", "DMZ", WAF), ("board.com", "DMZ", BOARD)} <= rows
    assert not [one for one in listed if one["address"].startswith("172.18.")], "no Docker bridge address"
    networks = {one["host"]: one["network"] for one in listed}
    assert networks["kali"] == ""
    assert networks["board.com"] == str(ipaddress.ip_interface(f"{BOARD}/24").network)

@pytest.mark.parametrize("lesson_id, step_id, url, status, right, wrong, reason", [
    ("f2", "path", "/search/?q=hello", 200, "/search/", "board.com/search/", "lesson.http.wrong.path.host"),
    ("f2", "path", "/search/?q=hello", 200, "/search/", "/search/?q=hello", "lesson.http.wrong.path.query"),
    ("f2", "path", "/search/?q=hello", 200, "/search/", "/search", "lesson.http.wrong.path.slash"),
    ("f2", "status", "/search/?q=hello", 200, "200 OK", "201", "lesson.check.wrong"),
    ("f2", "sort", "/?sort=title", 200, "sort", "q", "lesson.check.wrong"),
    ("f2", "missing", "/posts/9999/", 404, "404", "200", "lesson.check.wrong"),
    ("f5", "sort", "/?sort=-created_at", 200, "-created_at", "title", "lesson.check.wrong"),
    ("f5", "error", "/?sort=title)", 500, "500", "200", "lesson.check.wrong"),
])
def test_a_question_is_judged_from_the_learner_s_own_website_pane_request(client, lesson_id, step_id, url, status,
                                                                          right, wrong, reason):
    session = opened(lesson_id)
    before = answer(client, session, step_id, right)
    with patch.object(site, "kept", return_value=[browsed("/search/?q=hello", 200, request_id=0), browsed(url, status)]):
        judged = {given: answer(client, session, step_id, given) for given in (right, wrong)}

    assert (before["passed"], before["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert (judged[right]["passed"], judged[wrong]["passed"], judged[wrong]["reason"]) == (True, False, [reason, []])

def test_f3_reads_the_two_legs_of_one_search_by_destination_and_counts_both_legs_of_each_search(client):
    session = opened("f3")
    marker = session.browse_marker
    searched = [browsed("/search/?q=kim2026", 200), browsed("/search/?q=lee2026", 200, request_id=2)]
    legs = [event for word in ("kim2026", "lee2026") for event in (
        http_event(marker, f"/search/?q={word}", 200, host="cr-edge", src_ip=CUSTOMER, dest_ip=WAF, dest_port=80),
        http_event(marker, f"/search/?q={word}", 200, src_ip=WAF, dest_ip=BOARD, xff=CUSTOMER))]
    with on_the_range(), on_map(read_slot()), patch.object(site, "kept", return_value=searched), indexed(*legs):
        step(client, session, "search")
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("site_source", WAF), ("xff", CUSTOMER), ("count", "2"))}
        written = f"url : *lee2026* and not destination : {WAF}"
        counted = {query: step(client, session, "upstream", body={"answer": "1", "query": query}).json()
                   for query in (written, "url : *lee2026*", "")}
        wrong = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("site_source", CUSTOMER), ("xff", WAF), ("count", "1"))}
        upstream_wrong = step(client, session, "upstream", body={"answer": "2", "query": written}).json()["passed"]

    assert said == {"site_source": True, "xff": True, "count": True}, (
        "a count reads the newest search word, not another learner's or an older one")
    assert counted[written]["passed"] is True
    assert [(counted[query]["passed"], counted[query]["reason"]) for query in ("url : *lee2026*", "")] == [
        (False, ["lesson.logs.wrong.upstream.kql", []])] * 2, (
        "the right number read off the step before's table without the and-not query does not pass")
    assert wrong == {"site_source": False, "xff": False, "count": False} and upstream_wrong is False

def test_f4_reads_the_probe_s_block_score_and_whether_the_ids_alerted_from_the_session_s_records(client):
    session = opened("f4")
    probes = [browsed("/search/?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E", 403),
              browsed("/search/?q=%3CScRiPt%3Ealert(1)%3C%2FScRiPt%3E", 403, request_id=2)]
    for position, rule in enumerate(("941100", "941110")):
        detected(session, f"m{position}", "modsecurity", session.browse_marker, "XSS", details={"ruleId": rule})
    detected(session, "total", "modsecurity", session.browse_marker,
             "Inbound Anomaly Score Exceeded (Total Score: 20)", details={"ruleId": "949110"})
    with patch.object(site, "kept", return_value=probes), quietly():
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("encoded", "%3c"), ("upper", "20"), ("score", "20"), ("ids_none", "absent"))}
        unencoded = answer(client, session, "encoded", "<")
        whole = answer(client, session, "encoded", "%3Cscript")
        detected(session, "ids", "suricata", session.browse_marker, "script tag", alert={"signature_id": 9100001})
        alerted = answer(client, session, "ids_none", "present")["passed"]

    assert said == {"encoded": True, "upper": True, "score": True, "ids_none": True}
    assert unencoded["reason"] == ["lesson.xss.wrong.encoded.same", []]
    assert whole["reason"] == ["lesson.xss.wrong.encoded.more", []]
    assert alerted is True

NOCASE_LESS = 'alert http any any -> any any (msg:"script"; http.uri; content:"<script"; sid:9100001; rev:1;)\n'
WITH_NOCASE = 'alert http any any -> any any (msg:"script"; http.uri; content:"<script"; nocase; sid:9100001; rev:2;)\n'

def test_the_learner_s_rule_is_judged_by_its_own_alerts_and_the_fix_needs_nocase(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", write=timezone.now() - timedelta(minutes=1))
    after = [browsed("/search/?q=%3Cscript%3E", 403), browsed("/search/?q=%3CScRiPt%3E", 403, request_id=2)]
    detected(session, "mine", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
             http={"url": "/search/?q=%3Cscript%3E"}, dest_ip=WAF)
    detected(session, "posture", "suricata", session.browse_marker, "sqli", alert={"signature_id": 9000001},
             http={"url": "/search/?q=%3Cscript%3E"}, dest_ip=BOARD)
    with patch.object(site, "kept", return_value=after[:1]), quietly(), \
            patch("api.views._live_rules", lambda session=None: posture + NOCASE_LESS):
        sid = answer(client, session, "fired", "9100001")["passed"]
        board = answer(client, session, "fired", BOARD)["passed"]
        fired = answer(client, session, "fired", WAF)["passed"]
        without = step(client, session, "nocase").json()["passed"]
    with patch.object(site, "kept", return_value=after), quietly(), \
            patch("api.views._live_rules", lambda session=None: posture + WITH_NOCASE):
        with_nocase = step(client, session, "nocase").json()["passed"]

    assert (fired, without, with_nocase) == (True, False, True)
    assert (sid, board) == (False, False), (
        "the step asks what the alert says, the destination of the learner's own rule's alert, not the sid they typed")

def test_the_nocase_fix_passes_only_with_its_rev_raised_over_the_rule_it_fixes(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    RuleSet.objects.create(session=session, content=posture + NOCASE_LESS, applied_at=timezone.now() - timedelta(minutes=2))
    same_rev = WITH_NOCASE.replace("rev:2;", "rev:1;")
    RuleSet.objects.create(session=session, content=posture + same_rev, applied_at=timezone.now() - timedelta(minutes=1))
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + same_rev):
        kept = step(client, session, "nocase").json()
    RuleSet.objects.create(session=session, content=posture + WITH_NOCASE, applied_at=timezone.now())
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + WITH_NOCASE):
        raised = step(client, session, "nocase").json()
    fresh = opened("f4")
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + same_rev):
        written_with_nocase = step(client, fresh, "nocase").json()

    assert (kept["passed"], kept["reason"]) == (False, ["lesson.xss.fail.nocase.rev", ["9100001"]])
    assert raised["passed"] is True
    assert written_with_nocase["passed"] is True, "a rule written with nocase from the start has no case-sensitive rev to raise"

@pytest.mark.parametrize("rule, alerted, chosen, line", [
    (NOCASE_LESS, False, "absent", "lesson.xss.ok.slipped"),
    (WITH_NOCASE, True, "present", "lesson.xss.ok.slipped.present"),
], ids=["missed", "already-nocase"])
def test_the_slipped_pass_line_follows_the_answer_the_learner_s_own_rule_made_true(client, rule, alerted, chosen, line):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", write=timezone.now() - timedelta(minutes=1))
    if alerted:
        detected(session, "mine", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
                 http={"url": "/search/?q=%3CScRiPt%3E"})
    with patch.object(site, "kept", return_value=[browsed("/search/?q=%3CScRiPt%3E", 403)]), quietly(), \
            patch("api.views._live_rules", lambda session=None: posture + rule):
        judged = answer(client, session, "slipped", chosen)

    assert judged["passed"] is True, judged
    assert judged["progress"]["slipped"]["ok"] == strings.line(line), (
        "the pass line contradicts the answer the learner's own rule made true"
    )

COPIED = ('alert http any any -> any any (msg:"admin page request"; flow:established,to_server; http.uri; '
          'content:"/admin"; sid:9100001; rev:1;)\n')
SCRIPT_SEARCH = "/search/?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"

def ruled(content):
    return patch("api.views._live_rules", lambda session=None: content)

def test_f4_write_passes_only_when_the_learner_s_own_rule_alerted_on_a_script_search_sent_after_applying_it(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    applied = timezone.now() - timedelta(minutes=1)
    RuleSet.objects.create(session=session, content=posture + COPIED, applied_at=applied)
    RuleSet.objects.create(content=posture, applied_at=timezone.now())
    before = browsed(SCRIPT_SEARCH, 403, at=(applied - timedelta(minutes=1)).timestamp())
    search = browsed(SCRIPT_SEARCH, 403, request_id=2)
    logged = http_event(session.browse_marker, SCRIPT_SEARCH, 403, host="cr-edge", src_ip=CUSTOMER, dest_ip=WAF,
                        dest_port=80)
    with quietly():
        with ruled(posture), patch.object(site, "kept", return_value=[search]):
            unwritten = step(client, session, "write").json()
        with ruled(posture + COPIED):
            with patch.object(site, "kept", return_value=[before]), indexed():
                unsent = step(client, session, "write").json()
            with patch.object(site, "kept", return_value=[before, search]):
                with indexed():
                    unlogged = step(client, session, "write").json()
                with indexed(logged):
                    silent = step(client, session, "write").json()
                    admin = detected(session, "admin", "suricata", None, "admin page request",
                                     alert={"signature_id": 9100001}, http={"url": "/admin/"})
                    Detection.objects.filter(pk=admin.pk).update(timestamp=applied + timedelta(seconds=10))
                    elsewhere = step(client, session, "write").json()
        with ruled(posture + NOCASE_LESS), patch.object(site, "kept", return_value=[before, search]), indexed(logged):
            detected(session, "mine", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
                     http={"url": SCRIPT_SEARCH})
            fired = step(client, session, "write").json()

    assert (unwritten["passed"], unwritten["reason"]) == (False, ["lesson.xss.fail.write", []])
    assert unsent["reason"] == ["lesson.xss.fail.write.unsent", []], "a search sent before the rule was applied does not count"
    assert unlogged["reason"] == ["lesson.check.unrecorded", []], "no sensor log of the search yet means check again soon"
    assert (silent["passed"], silent["reason"]) == (False, ["lesson.xss.fail.write.silent", ["9100001"]]), (
        "the copied /admin example is a valid rule that does not alert on <script")
    assert elsewhere["reason"] == ["lesson.xss.fail.write.elsewhere", ["9100001", "/admin/"]]
    assert fired["passed"] is True and fired["added"] == [9100001]

def test_the_suricata_reference_gives_a_rule_form_to_fill_in_and_no_complete_rule_for_something_else():
    table = tables()
    body = table["lesson.ref.suricata.body"]
    shown = [line for line in body.split("\n") if line.startswith("alert ")]
    assert len(shown) == 1 and "9100001;" not in body and "/admin" not in body
    assert re.search(r'msg:"\[[^]]+\]";.*content:"\[[^]]+\]";.*sid:\[[^]]+\];', shown[0])

def test_a_logged_search_that_drew_no_alert_from_the_rule_says_so_instead_of_asking_for_a_log(client):
    session = opened("f4")
    passed(session, "f4", write=timezone.now() - timedelta(minutes=1))
    searched = [browsed("/search/?q=%3Cscript%3E", 403)]
    with patch.object(site, "kept", return_value=[]), quietly():
        unsent = answer(client, session, "fired", WAF)
    with patch.object(site, "kept", return_value=searched), quietly():
        silent = answer(client, session, "fired", WAF)

    assert unsent["reason"] == ["lesson.check.unrecorded", []]
    assert (silent["passed"], silent["reason"]) == (False, ["lesson.xss.fail.fired", []])

def test_the_f5_sqlmap_step_accepts_a_run_with_a_random_user_agent(client):
    session = opened("f5")
    with patch("api.views.attacker.set_label"):
        step(client, session, "sqlmap", tail="", body={"state": "reached"})
    marker = Session.objects.get(pk=session.pk).lesson_steps["f5"]["sqlmap"]["marker"]
    settled = timezone.now() - timedelta(seconds=20)
    run = [http_event(marker, f"/?sort=posts_post.id{n}", 403, host="cr-edge", agent="Opera/9.21",
                       src_ip=KALI, dest_ip=WAF, at=settled) for n in range(3)]
    with indexed(*run), quietly():
        ran = step(client, session, "sqlmap").json()

    assert ran["passed"] is True

def test_every_run_step_waits_for_a_shell_prompt_ending_in_a_dollar_or_a_hash_and_not_for_text_in_the_output():
    waits = [shown["point"]["term"]["match"] for taught in wargames.foundations("board") for shown in taught["steps"]
             if shown["point"].get("term", {}).get("match", "").endswith(" $")]

    assert len(waits) == 4
    for wanted in waits:
        found = re.compile(wanted)
        assert all(found.search(prompt) for prompt in ("└─$ ", "└─# ", "root@kali:~# "))
        assert not any(found.search(text) for text in ("# comment line", "costs $5 each", "sqlmap resumed #1 run"))

def test_a_replay_passes_only_when_the_attack_after_the_fix_alerts_and_an_ordinary_search_still_passes(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", nocase=timezone.now() - timedelta(minutes=1))
    mixed, plain = browsed("/search/?q=%3CScRiPt%3E", 403), browsed("/search/?q=hello", 200, request_id=2)
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + WITH_NOCASE):
        with patch.object(site, "kept", return_value=[mixed, plain]):
            unalerted = step(client, session, "replay").json()
        detected(session, "mine", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001})
        with patch.object(site, "kept", return_value=[mixed]):
            no_benign = step(client, session, "replay").json()
        with patch.object(site, "kept", return_value=[mixed, dict(plain, at=time.time() + 30)]):
            done = step(client, session, "replay").json()

    assert unalerted["reason"] == ["lesson.check.replay_attack", []]
    assert no_benign["reason"] == ["lesson.check.replay_benign", []]
    assert done["passed"] is True

def test_a_replay_s_ordinary_search_seconds_after_the_attack_is_not_charged_with_the_attack_s_alert(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", nocase=timezone.now() - timedelta(minutes=1))
    mixed = browsed("/search/?q=%3CScRiPt%3Ealert(1)%3C%2FScRiPt%3E", 403)
    plain = browsed("/search/?q=walrus2290", 200, request_id=2, at=mixed["at"] + 3.5)
    detected(session, "mine", "suricata", session.browse_marker, "XSS", alert={"signature_id": 9100001},
             http={"url": "/search/?q=%3CScRiPt%3Ealert%281%29%3C%2FScRiPt%3E"})
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + WITH_NOCASE):
        with patch.object(site, "kept", return_value=[mixed, plain]):
            judged = step(client, session, "replay").json()

    assert judged["passed"] is True

def test_a_step_says_it_has_a_command_before_it_is_reached_and_gives_the_text_only_once_reached(client):
    session = opened("f6")
    before = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}
    with patch("api.views.attacker.set_label"):
        step(client, session, "replay", tail="", body={"state": "reached"})
    after = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert (before["replay"]["has_command"], "command" in before["replay"]) == (True, False)
    assert (before["loot"]["has_command"], "command" in before["loot"]) == (False, False)
    assert after["replay"]["command"].startswith("sqlmap ")

def test_a_kali_step_writes_its_marker_to_the_stamp_proxy_shows_no_runnable_command_and_passes_on_that_marker(client):
    session = opened("f5")
    with patch("api.views.attacker.set_label") as labelled:
        step(client, session, "agent", tail="", body={"state": "reached"})
    marker = Session.objects.get(pk=session.pk).lesson_steps["f5"]["agent"]["marker"]
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}
    settled = timezone.now() - timedelta(seconds=20)
    run = [http_event(marker, f"/?sort=posts_post.id{n}", 403, host="cr-edge", agent="Opera/9.21",
                       src_ip=KALI, dest_ip=WAF, at=settled) for n in range(3)]
    fresh = http_event(marker, "/?sort=posts_post.id9", 403, host="cr-edge", agent="Opera/9.21", src_ip=KALI, dest_ip=WAF)
    with indexed(), quietly():
        early = step(client, session, "agent").json()
    with indexed(*run, fresh), quietly():
        running = step(client, session, "agent").json()
    with indexed(*run), quietly():
        ran = step(client, session, "agent").json()

    assert labelled.call_args.args[0] == marker
    assert "--headers" not in shown["agent"]["command"] and "--random-agent" in shown["agent"]["command"]
    assert (early["passed"], early["reason"]) == (False, ["lesson.check.kali_none", ["sqlmap"]])
    assert (running["passed"], running["reason"]) == (False, ["lesson.check.kali_settling", ["sqlmap"]]), (
        "a request seconds ago means the logs are still settling")
    assert ran["passed"] is True and set(ran["kali"]) == {"name", "discover"}, "no request count, no sensor names"
    recorded = Case.objects.get(session=session, case_id=marker)
    assert recorded.malicious and (recorded.meta["kali"], recorded.meta["lesson"]) == ("agent", "f5")
    assert "--headers" not in recorded.meta["command"]

def test_f5_reads_the_verdict_from_sqlmap_s_own_log_and_the_run_s_source_and_rules_from_its_marker(client):
    session = opened("f5")
    run = kali_run(session, "f5", "sqlmap", "run-1")
    detected(session, "a", "modsecurity", "run-1", "scanner", src_ip=KALI, details={"ruleId": "913100"},
             request={"uri": "/?sort=posts_post.id"})
    detected(session, "b", "modsecurity", "run-1", "sqli", src_ip=KALI, details={"ruleId": "942100"},
             request={"uri": "/?sort=posts_post.id"})
    logs = []

    def kali(argv, stdin=None, timeout=60.0):
        logs.append(argv[-1])
        return Ran(0, "")

    window = [waf_record("run-1", "/?sort=posts_post.id") for _ in range(3)] + [waf_record("other", "/?sort=title)")]
    with quietly(), one_slot(lambda adapter, role, segment_id="": kali), indexed(*window):
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("verdict", "no"), ("source", "4"), ("scanner", "913100"))}
        own = answer(client, session, "source", "3")["passed"]
        unqueried = answer(client, session, "source", "4", query="")["reason"]
        family = answer(client, session, "scanner", "942100")["passed"]
        address = answer(client, session, "source", KALI)["reason"]

    assert said == {"verdict": True, "source": True, "scanner": True}
    assert own is True, "the run's own records count, as does the window Kibana opens"
    assert unqueried == ["lesson.sqli.wrong.source.kql", []], "the count is read in Kibana, not guessed"
    assert address == ["lesson.sqli.wrong.source.address", []], "kali's address is on the map; the question is the count"
    assert family is False, "the scanner question keeps the 913 family only"
    assert "/.local/share/sqlmap/output/board.com/log" in logs[0]
    assert run.case_id == "run-1"

def test_f6_reads_the_exception_the_alerts_the_attack_drew_and_the_errors_it_caused_from_the_run(client):
    session = opened("f6")
    kali_run(session, "f6", "dump", "dump-1")
    edge = [http_event("dump-1", f"/?sort=posts_post.id{n}", status, host="cr-edge", src_ip=KALI, dest_ip=WAF,
                       dest_port=80) for n, status in enumerate((500, 500, 200))]
    upstream = [http_event("dump-1", f"/?sort=posts_post.id{n}", status, src_ip=WAF, dest_ip=BOARD)
                for n, status in enumerate((500, 500, 200))]
    logged = [{"event": {"module": "modsecurity"}, "@timestamp": edge[0]["timestamp"],
               "transaction": {"client_ip": KALI, "request": {"headers": {}}, "response": {"http_code": status}}}
              for status in (500, 500, 500, 403)]
    standing = {"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}
    with quietly(), on_map(read_slot()), on_the_range(), indexed(*edge, *upstream, *logged), \
            patch("api.views._waf_in_force", lambda session: standing):
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("excluded", "sort"), ("alerts", "none"), ("seen", "3"))}
        the_waf = answer(client, session, "seen", "4")["passed"]
        detected(session, "ids", "suricata", "dump-1", "SQLi", alert={"signature_id": 9000003})
        ids_only = answer(client, session, "alerts", "ids")["passed"]

    assert said == {"excluded": True, "alerts": True, "seen": True}
    assert the_waf is False, "a 403 record is not a server error"
    assert ids_only is True

def test_the_penalty_counts_double_for_an_objective_lost_undetected_since_the_lesson_started(client):
    session = opened("f5", lessons=[{"id": "f5", "started_at": timezone.now().isoformat()}])
    Objective.objects.create(session=session, key="board-auth-user-partial", name="partial", difficulty=2,
                             achieved_at=timezone.now() - timedelta(minutes=1))
    with one_slot(Stand()), patch("api.views.harness.fire", attacker({})[0]):
        client.post_json(f"/api/sessions/{session.pk}/lesson/", {"lesson": "f6"})
    for key, difficulty in (("board-auth-user-admin", 4), ("board-auth-user-full", 5)):
        Objective.objects.create(session=session, key=key, name=key, difficulty=difficulty,
                                 achieved_at=timezone.now() + timedelta(seconds=1))
    with quietly():
        total = answer(client, session, "cost", "18")["passed"]
        right = answer(client, session, "cost", "4")["passed"]
        card = client.get(f"/api/sessions/{session.pk}/").json()["lesson_objectives"]

    assert (total, right) == (False, True), "the question asks what admin would have cost detected, not the printed total"
    assert card["total"] == 18, "2 x (4 + 5): F5's loss is not F6's"
    assert [(row["id"], row["lost"], row["points"]) for row in card["rows"]] == [
        ("board-auth-user-partial", False, 0), ("board-auth-user-admin", True, 8), ("board-auth-user-full", True, 10)]

def test_narrowing_passes_once_the_declared_exception_is_gone_from_the_waf_s_file(client):
    session = opened("f6")
    broad = {"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}
    narrow = {"paranoia": 1, "exclusions": [{"rule_id": 942100, "target": "ARGS:q", "path": "/search/"}]}
    with patch("api.views._waf_in_force", lambda session: broad):
        kept = step(client, session, "narrow").json()["passed"]
    with patch("api.views._waf_in_force", lambda session: narrow):
        removed = step(client, session, "narrow").json()["passed"]

    assert (kept, removed) == (False, True)

def test_the_f6_replay_needs_the_run_blocked_with_no_loot_and_an_ordinary_sort_unlogged(client):
    session = opened("f6")
    passed(session, "f6", narrow=timezone.now() - timedelta(minutes=2))
    kali_run(session, "f6", "replay", "replay-1")
    sorted_ = browsed("/?sort=title", 200)
    with quietly(), indexed(), patch.object(site, "kept", return_value=[sorted_]):
        unblocked = step(client, session, "replay").json()
        detected(session, "block", "modsecurity", "replay-1", "total", details={"ruleId": "949110"})
        done = step(client, session, "replay").json()
    with quietly(), indexed(waf_record(session.browse_marker, "/?sort=title")), \
            patch.object(site, "kept", return_value=[sorted_]):
        logged = step(client, session, "replay").json()

    assert unblocked["reason"] == ["lesson.check.replay_attack", []]
    assert done["passed"] is True
    assert logged["reason"] == ["lesson.check.replay_benign.waf_logged", ["/?sort=title"]], (
        "an ordinary sort the WAF logged is no fix, and the learner is told which request")
    assert logged["loud"] is True

def test_loot_from_the_dump_is_judged_by_the_board_s_own_accounts(client):
    session = opened("f6")
    kali_run(session, "f6", "dump", "kali-run")
    forged = DUMPED.replace("jiwoo    | pbkdf2_sha256$260000$q", "jiwoo    | pbkdf2_sha256$260000$X")
    with quietly():
        handed = step(client, session, "loot", body={"answer": forged}).json()
        whole = step(client, session, "loot", body={"answer": DUMPED}).json()

    assert handed["passed"] is False and handed["loot"]["matched"] == ["admin", "minseo"]
    assert handed["reason"] == ["lesson.miss.fail.loot.partial", [2, 3]], "a partial table says what is missing"
    assert whole["passed"] is True and whole["loot"]["matched"] == ["admin", "jiwoo", "minseo"], (
        "the box stays open after a partial paste, and the whole table passes")

@pytest.mark.parametrize("check, reason", [
    ({"kind": "answer", "of": "status"}, "read from the record"),
    ({"kind": "answer", "of": "sqlmap_found", "about": "one"}, "read from the record"),
    ({"kind": "answer", "of": "rule", "marker": "step:one"}, "read from the record"),
    ({"kind": "choice", "of": "rule_matched", "marker": "browse", "path": "x", "options": ["present", "absent"]},
     "needs rule:"),
    ({"kind": "answer", "of": "status", "match": "("}, "read from the record"),
    ({"kind": "answer", "of": "status", "match": "x", "wrong_if": [{"match": "(", "says": "x"}]}, "wrong_if"),
    ({"kind": "answer", "of": "sensor_source", "match": "x", "leg": "sideways"}, "leg"),
    ({"kind": "sent", "match": "("}, "match"),
    ({"kind": "loot", "about": "one"}, "about"),
    ({"kind": "kali", "case": "no-such-case"}, "tool case"),
    ({"kind": "replay", "after": "one", "attack": {"sent": "x"}}, "replay"),
    ({"kind": "replay", "after": "one", "attack": {"kali": "no-such-case"}, "benign": {"sent": "x"}}, "tool case"),
    ({"kind": "waf_changed"}, "removed_target"),
])
def test_a_foundation_that_could_not_be_judged_is_refused_at_discovery(settings, tmp_path, check, reason):
    folder = tmp_path / "wargames" / "demo"
    folder.mkdir(parents=True)
    taught = [{"id": "a", "order": 1, "text": "lesson.demo", "cases": ["board-normal-search"],
               "steps": [{"id": "one", "check": {"kind": "click"}}, {"id": "two", "check": check}]}]
    (folder / "scenario.yaml").write_text(yaml.safe_dump({**A_SCENARIO, "foundations": taught}))
    settings.CR_SOURCE = str(tmp_path)

    with pytest.raises(wargames.InvalidCatalogue, match=reason):
        wargames._discover()

def test_after_a_switch_a_lesson_judges_only_what_the_learner_did_since_it_started(client):
    session = opened("f2", lessons=[{"id": "f2", "started_at": timezone.now().isoformat()}])
    earlier = browsed("/search/?q=kim2026", 200)
    with patch.object(site, "kept", return_value=[earlier]):
        passed_in_f2 = step(client, session, "search").json()["passed"]
    with patch("api.views.harness.fire", attacker({})[0]):
        client.post_json(f"/api/sessions/{session.pk}/lesson/", {"lesson": "f3"})
    with patch.object(site, "kept", return_value=[earlier]):
        before = step(client, session, "search").json()
    with patch.object(site, "kept", return_value=[earlier, browsed("/search/?q=lee2026", 200, 2, at=time.time() + 1)]):
        after = step(client, session, "search").json()

    assert passed_in_f2 is True
    assert before["passed"] is False, "F2's search was made before F3 started"
    assert after["passed"] is True
    assert set(Session.objects.get(pk=session.pk).lesson_steps) == {"f2", "f3"}

BROAD = 'alert http any any -> any any (msg:"search"; http.uri; content:"/search/"; sid:9100001; rev:1;)\n'
BROAD_NOCASE = 'alert http any any -> any any (msg:"search"; http.uri; content:"/search/"; nocase; sid:9100001; rev:2;)\n'

def test_a_rule_that_would_alert_on_every_plain_search_fails_the_write_and_the_nocase_steps_with_the_reason(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    RuleSet.objects.create(session=session, content=posture + BROAD, applied_at=timezone.now() - timedelta(minutes=1))
    search = browsed(SCRIPT_SEARCH, 403)
    detected(session, "mine", "suricata", session.browse_marker, "search", alert={"signature_id": 9100001},
             http={"url": SCRIPT_SEARCH})
    plain = "/search/?q=release notes"
    with quietly(), patch.object(site, "kept", return_value=[search]):
        with ruled(posture + BROAD), indexed():
            written = step(client, session, "write").json()
        with ruled(posture + BROAD_NOCASE):
            fixed = step(client, session, "nocase").json()
        with ruled(posture + WITH_NOCASE):
            narrow = step(client, session, "nocase").json()

    assert (written["passed"], written["reason"]) == (False, ["lesson.xss.fail.write.broad", ["9100001", plain]]), (
        "a rule that alerts on the attack and on every plain search does not pass")
    assert fixed["reason"] == ["lesson.xss.fail.nocase.broad", ["9100001", plain]]
    assert narrow["passed"] is True

def test_a_broad_rule_is_told_the_plain_search_it_actually_matches(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    hello = 'alert http any any -> any any (msg:"hello"; http.uri; content:"hello"; nocase; sid:9100001; rev:2;)\n'
    with quietly(), ruled(posture + hello):
        judged = step(client, session, "nocase").json()

    assert judged["reason"] == ["lesson.xss.fail.nocase.broad", ["9100001", "/search/?q=hello"]]

def test_a_rule_with_no_uri_content_is_not_judged_broad_on_a_uri():
    header_only = 'alert http any any -> any any (msg:"x"; http.header; content:"<script"; sid:9100001; rev:1;)'

    assert lesson.alerts_on(header_only, "/search/?q=hello") is False

def test_a_count_or_points_answer_with_its_unit_word_is_the_number():
    judged = {given: lesson.answered({"accept": ["20"]}, given, "w")[0] for given in ("20점", "20 점", "1,9점", "20%")}

    assert judged == {"20점": True, "20 점": True, "1,9점": False, "20%": False}

def test_a_devtools_question_needs_the_request_s_row_picked_in_devtools(client):
    session = opened("f2")
    kept = [browsed("/", 200, request_id=0), browsed("/search/?q=hello", 200)]
    with patch.object(site, "kept", return_value=kept):
        unpicked = answer(client, session, "method", "GET", dev_request=None)
        other_row = answer(client, session, "method", "GET", dev_request=0)
        picked = answer(client, session, "method", "GET", dev_request=1)

    assert unpicked["reason"] == other_row["reason"] == ["lesson.check.wrong.dev", []]
    assert picked["passed"] is True

def test_a_replay_whose_plain_search_drew_the_learner_s_rule_says_so_at_once_instead_of_checking_forever(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", nocase=timezone.now() - timedelta(minutes=1))
    mixed, plain = browsed("/search/?q=%3CScRiPt%3E", 403), browsed("/search/?q=hello", 200, request_id=2)
    detected(session, "attack", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
             http={"url": "/search/?q=%3CScRiPt%3E"})
    detected(session, "plain", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
             http={"url": "/search/?q=hello"})
    with quietly(), patch("api.views._live_rules", lambda session=None: posture + BROAD_NOCASE), \
            patch.object(site, "kept", return_value=[mixed, plain]):
        judged = step(client, session, "replay", body={"poll": True}).json()

    assert judged["passed"] is False
    assert judged["reason"] == ["lesson.check.replay_benign.alerted", ["9100001", "/search/?q=hello"]]
    assert judged["loud"] is True, "a definite fault is shown even on a silent poll"

@pytest.mark.parametrize("standing, reason", [
    ({"paranoia": None, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}, "paranoia"),
    ({"paranoia": None, "exclusions": []}, "paranoia"),
    ({"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}, "kept"),
    ({"paranoia": 1, "exclusions": []}, None),
], ids=["level-deleted", "both-deleted", "untouched", "sort-deleted"])
def test_narrowing_keeps_the_paranoia_level_line_and_says_so_when_it_was_deleted(client, standing, reason):
    session = opened("f6")
    with patch("api.views._waf_in_force", lambda session: standing):
        judged = step(client, session, "narrow", body={"poll": True}).json()

    if reason is None:
        assert judged["passed"] is True
    elif reason == "paranoia":
        assert judged["passed"] is False and judged["loud"] is True
        assert judged["reason"][0] == "lesson.miss.fail.narrow.paranoia"
        assert "tx.blocking_paranoia_level=1" in judged["reason"][1][0], "the line to put back is given"
    else:
        assert judged["reason"] == ["lesson.miss.fail.narrow", []]

@pytest.mark.parametrize("lost, seen, line", [
    (True, False, "lesson.miss.ok.cost.undetected"),
    (True, True, "lesson.miss.ok.cost.detected"),
    (False, False, "lesson.miss.ok.cost.kept"),
], ids=["lost-unseen", "lost-seen", "kept"])
def test_the_cost_pass_line_states_what_happened_to_the_admin_account(client, lost, seen, line):
    session = opened("f6")
    breach = SimpleNamespace(key="board-auth-user-admin", detected=seen)
    with quietly(), patch("api.views._breaches", lambda session, cases, result: [breach] if lost else []):
        judged = answer(client, session, "cost", "4")

    assert judged["passed"] is True
    assert judged["progress"]["cost"]["ok"] == strings.line(line)

def test_a_wrong_map_address_says_it_is_another_device_s_without_naming_it_and_a_log_step_says_which_row(client):
    session = opened("f1")
    with on_the_range(), on_map(read_slot()):
        mapped = answer(client, session, "board_ip", WAF)
    reading = opened("f3")
    searched = browsed("/search/?q=kim0413", 200)
    logged = http_event(reading.browse_marker, "/search/?q=kim0413", 200, src_ip=WAF, dest_ip=BOARD)
    with on_the_range(), on_map(read_slot()), patch.object(site, "kept", return_value=[searched]), indexed(logged), \
            quietly():
        read = answer(client, reading, "site_source", KALI)

    assert mapped["reason"] == ["lesson.check.wrong.address_of", []], "the waf address is the last step's answer"
    assert read["reason"] == ["lesson.logs.wrong.site_source.row", []]

def test_a_step_passed_after_a_wrong_answer_is_counted_as_retried(client):
    session = opened("f6")
    standing = {"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}
    with patch("api.views._waf_in_force", lambda session: standing):
        prefixed = answer(client, session, "excluded", "ARGS:sort")["reason"]
        answer(client, session, "excluded", "sort")
    session.refresh_from_db()

    assert prefixed == ["lesson.miss.wrong.excluded.prefix", []]
    assert lesson.help_counts(session.lesson_steps["f6"])["retried"] == 1
