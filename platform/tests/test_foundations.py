import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from django.test import override_settings
from django.utils import timezone

import wargames
from api import site
from api.models import Case, Detection, Objective, Session
from range import declared
from range.ports import Ran
from tests.test_gns3_maps import DOCKER_FOUND, read_slot
from tests.test_lesson_api import DUMPED, TRUTH, Stand, attacker
from tests.test_scenario_discovery import A_SCENARIO
from tests.test_strings import tables

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGIES = {flavor: ROOT / "deploy" / "topology" / f"range-{flavor}.gns3" for flavor in ("docker", "openstack")}
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

def answer(client, session, step_id, given):
    return step(client, session, step_id, body={"answer": given}).json()

def browsed(url, status, request_id=1, ms=40, at=None):
    return {"id": request_id, "at": at or time.time(), "method": "GET", "url": f"http://board.com{url}",
            "status": status, "blocked": status == 403, "ms": ms}

def http_event(marker, url, status, host="fsl-wargame-host", agent="Mozilla/5.0", event_type="http", **fields):
    headers = [{"name": "X-FSL-Case", "value": marker}] if marker else []
    headers += [{"name": "X-Forwarded-For", "value": fields["xff"]}] if fields.get("xff") else []
    return {"fsl_source": "suricata", "event_type": event_type, "timestamp": (fields.get("at") or timezone.now()).isoformat(),
            "src_ip": fields.get("src_ip", WAF), "dest_ip": fields.get("dest_ip", BOARD),
            "dest_port": fields.get("dest_port", 8000), "log": {"syslog": {"hostname": host}},
            "http": {"url": url, "status": status, "http_method": "GET", "http_user_agent": agent,
                     "request_headers": headers}}

def waf_record(marker, uri):
    return {"fsl_source": "modsecurity", "@timestamp": timezone.now().isoformat(),
            "transaction": {"client_ip": CUSTOMER, "request": {"uri": uri, "headers": {"X-FSL-Case": marker}},
                            "messages": []}}

def indexed(*events):
    return patch("api.views._fetched", lambda index, start, end, newest_first: (
        [(f"doc-{position}", event) for position, event in enumerate(events)], None))

def quietly():
    return patch("api.views._ingest", lambda session, within=None: {})

def on_map(found):
    return patch("api.views._map_found", lambda session: found)

def flavor(name):
    return override_settings(FSL_TOPOLOGY=TOPOLOGIES[name], RANGE=declared.read(flavor=name))

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

def test_every_foundation_has_its_words_in_both_languages():
    table = tables()
    for taught in wargames.foundations("board"):
        prefix, last = taught["text"], taught["steps"][-1]["id"]
        keys = [f"{prefix}.{part}" for part in ("title", "summary", "learns")]
        keys += [f"{prefix}.theory.{card['id']}.{part}" for card in taught["theory"] for part in ("title", "body")]
        for shown in taught["steps"]:
            check, named = shown["check"], shown["id"]
            keys += [f"{prefix}.{part}.{named}" for part in ("title", "coach", "ok")]
            keys += [f"{prefix}.label.{named}"] if check["kind"] in ("answer", "choice") else []
            keys += [f"{prefix}.{part}.{named}" for part in ("callout", "nudge", "hint")] if named != last else []
            keys += [f"lesson.choice.{option}" for option in check.get("options", [])]
            keys += [f"{prefix}.wrong.{named}.{code}" for code in [*check.get("known", []),
                                                                  *(rule["says"] for rule in check.get("wrong_if", []))]]
            keys += [f"{prefix}.wrong.{named}.order"] if check.get("form") == "order" else []
            keys += [f"lesson.open.{shown['point']['opens']}"]
        for language in ("en", "ko"):
            assert not [key for key in keys if key not in table[language]], (taught["id"], language)

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
            assert set(point.get("then") or {}) <= LOCATORS and len(point.get("then") or {"one": 1}) == 1
    Session.objects.filter(pk=session.pk).update(lesson="f6", defense="overbroad")
    steps = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]
    assert [one["solo"] for one in steps] == [False] * 7 + [True]

@pytest.mark.parametrize("name, found, board_ip, db_subnet, db_ip, route", [
    ("docker", DOCKER_FOUND, "172.30.0.5", "172.30.0.0/24", "172.30.0.6", "customers > waf > board.com"),
    ("openstack", None, BOARD, "172.18.0.0/16", "172.18.0.2", "customers > firewall > waf > board.com"),
])
def test_the_map_questions_are_answered_from_the_addresses_and_captions_the_learner_s_map_shows(
        client, name, found, board_ip, db_subnet, db_ip, route):
    session = opened("f1")
    with flavor(name), on_map(found if found is not None else read_slot()):
        given = {
            "board_ip": [answer(client, session, "board_ip", one)["passed"] for one in (board_ip, f"{board_ip}/24", WAF)],
            "db_subnet": [answer(client, session, "db_subnet", one)["passed"] for one in (db_subnet, db_ip)],
            "kali_zone": [answer(client, session, "kali_zone", one)["passed"] for one in ("인터넷망", "internet", "Services")],
            "log_host": [answer(client, session, "log_host", one)["passed"] for one in ("log-server", "waf")],
            "db_ip": [answer(client, session, "db_ip", one)["passed"] for one in (db_ip, board_ip)],
        }
        reordered = answer(client, session, "path", " > ".join(reversed(route.split(" > "))))
        right = answer(client, session, "path", route)
        shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert given == {"board_ip": [True, True, False], "db_subnet": [True, False], "kali_zone": [True, True, False],
                     "log_host": [True, False], "db_ip": [True, False]}
    assert reordered["reason"] == ["lesson.map.wrong.path.order", []], "right hosts in the wrong order say so"
    assert right["passed"] is True
    assert set(route.split(" > ")) <= set(shown["path"]["check"]["options"]) and "sw1" not in shown["path"]["check"]["options"]
    assert shown["db_subnet"]["point"]["map"] == {"zone": "sw1" if name == "docker" else "sw2"}

@pytest.mark.parametrize("lesson_id, step_id, url, status, right, wrong, reason", [
    ("f2", "path", "/search/?q=hello", 200, "/search/", "board.com/search/", "lesson.http.wrong.path.host"),
    ("f2", "path", "/search/?q=hello", 200, "/search", "/search/?q=hello", "lesson.http.wrong.path.query"),
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

def test_f3_reads_the_two_legs_of_one_search_by_destination_so_one_sensor_seeing_both_counts_each_search_once(client):
    session = opened("f3")
    marker = session.browse_marker
    searched = [browsed("/search/?q=kim2026", 200), browsed("/search/?q=lee2026", 200, request_id=2)]
    legs = [event for word in ("kim2026", "lee2026") for event in (
        http_event(marker, f"/search/?q={word}", 200, host="fsl-edge", src_ip=CUSTOMER, dest_ip=WAF, dest_port=80),
        http_event(marker, f"/search/?q={word}", 200, src_ip=WAF, dest_ip=BOARD, xff=CUSTOMER))]
    with flavor("openstack"), on_map(read_slot()), patch.object(site, "kept", return_value=searched), indexed(*legs):
        step(client, session, "search")
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("site_source", WAF), ("client_source", CUSTOMER), ("xff", CUSTOMER), ("count", "2"))}
        Session.objects.filter(pk=session.pk).update(lesson_steps={"f3": {"site_source": {"passed": "x"}}})
        host = answer(client, session, "site_host", "waf")["passed"]
        wrong = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("site_source", CUSTOMER), ("client_source", WAF), ("count", "4"))}

    assert said == {"site_source": True, "client_source": True, "xff": True, "count": True}
    assert host is True, "the host is the map host whose address the step before found"
    assert wrong == {"site_source": False, "client_source": False, "count": False}

def test_whether_a_search_is_in_the_waf_log_is_read_from_the_waf_s_own_records(client):
    session = opened("f3")
    with patch.object(site, "kept", return_value=[browsed("/search/?q=kim2026", 200)]):
        with indexed():
            quiet = answer(client, session, "waf_logged", "absent")["passed"]
        with indexed(waf_record(session.browse_marker, "/search/?q=kim2026")):
            logged = answer(client, session, "waf_logged", "present")["passed"]

    assert (quiet, logged) == (True, True)

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
            ("status", "403"), ("upper", "403"), ("score", "20"), ("ids_none", "absent"))}
        detected(session, "ids", "suricata", session.browse_marker, "script tag", alert={"signature_id": 9100001})
        alerted = answer(client, session, "ids_none", "present")["passed"]

    assert said == {"status": True, "upper": True, "score": True, "ids_none": True}
    assert alerted is True

NOCASE_LESS = 'alert http any any -> any any (msg:"script"; http.uri; content:"<script"; sid:9100001; rev:1;)\n'
WITH_NOCASE = 'alert http any any -> any any (msg:"script"; http.uri; content:"<script"; nocase; sid:9100001; rev:2;)\n'

def test_the_learner_s_rule_is_judged_by_its_own_alerts_and_the_fix_needs_nocase(client):
    session = opened("f4")
    posture = (ROOT / "deploy/suricata/rules/no-xss.rules").read_text()
    passed(session, "f4", write=timezone.now() - timedelta(minutes=1))
    after = [browsed("/search/?q=%3Cscript%3E", 403), browsed("/search/?q=%3CScRiPt%3E", 403, request_id=2)]
    detected(session, "mine", "suricata", session.browse_marker, "script", alert={"signature_id": 9100001},
             http={"url": "/search/?q=%3Cscript%3E"})
    with patch.object(site, "kept", return_value=after[:1]), quietly(), \
            patch("api.views._live_rules", lambda session=None: posture + NOCASE_LESS):
        fired = answer(client, session, "fired", "9100001")["passed"]
        without = step(client, session, "nocase").json()["passed"]
    with patch.object(site, "kept", return_value=after), quietly(), \
            patch("api.views._live_rules", lambda session=None: posture + WITH_NOCASE):
        with_nocase = step(client, session, "nocase").json()["passed"]

    assert (fired, without, with_nocase) == (True, False, True)

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

def test_a_kali_step_writes_its_marker_to_the_stamp_proxy_shows_no_runnable_command_and_passes_on_that_marker(client):
    session = opened("f5")
    with patch("api.views.attacker.set_label") as labelled:
        step(client, session, "agent", tail="", body={"state": "reached"})
    marker = Session.objects.get(pk=session.pk).lesson_steps["f5"]["agent"]["marker"]
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}
    settled = timezone.now() - timedelta(seconds=20)
    run = [http_event(marker, f"/?sort=posts_post.id{n}", 403, host="fsl-edge", agent="Opera/9.21",
                       src_ip=KALI, dest_ip=WAF, at=settled) for n in range(3)]
    fresh = http_event(marker, "/?sort=posts_post.id9", 403, host="fsl-edge", agent="Opera/9.21", src_ip=KALI, dest_ip=WAF)
    with indexed(), quietly():
        early = step(client, session, "agent").json()
    with indexed(*run, fresh), quietly():
        running = step(client, session, "agent").json()
    with indexed(*run), quietly():
        ran = step(client, session, "agent").json()

    assert labelled.call_args.args[0] == marker
    assert "--headers" not in shown["agent"]["command"] and "--random-agent" in shown["agent"]["command"]
    assert (early["passed"], early["reason"]) == (False, ["lesson.check.kali_none", ["sqlmap"]])
    assert (running["passed"], running["reason"]) == (False, ["lesson.check.kali_running", ["sqlmap"]]), (
        "a request seconds ago means the run is still going")
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

    with quietly(), patch("range.docker.Docker.runner", lambda adapter, role, segment_id="": kali):
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("verdict", "no"), ("source", KALI), ("scanner", "913100"))}
        family = answer(client, session, "scanner", "942100")["passed"]

    assert said == {"verdict": True, "source": True, "scanner": True}
    assert family is False, "the scanner question keeps the 913 family only"
    assert "/.local/share/sqlmap/output/board.com/log" in logs[0]
    assert run.case_id == "run-1"

def test_f6_reads_the_exception_the_alerts_the_attack_drew_and_the_errors_it_caused_from_the_run(client):
    session = opened("f6")
    kali_run(session, "f6", "dump", "dump-1")
    edge = [http_event("dump-1", f"/?sort=posts_post.id{n}", status, host="fsl-edge", src_ip=KALI, dest_ip=WAF,
                       dest_port=80) for n, status in enumerate((500, 500, 200))]
    upstream = [http_event("dump-1", f"/?sort=posts_post.id{n}", status, src_ip=WAF, dest_ip=BOARD)
                for n, status in enumerate((500, 500, 200))]
    standing = {"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort", "path": ""}]}
    with quietly(), on_map(read_slot()), flavor("openstack"), indexed(*edge, *upstream), \
            patch("api.views._waf_in_force", lambda session: standing):
        said = {name: answer(client, session, name, given)["passed"] for name, given in (
            ("excluded", "sort"), ("alerts", "none"), ("seen", "2"))}
        detected(session, "ids", "suricata", "dump-1", "SQLi", alert={"signature_id": 9000003})
        ids_only = answer(client, session, "alerts", "ids")["passed"]

    assert said == {"excluded": True, "alerts": True, "seen": True}
    assert ids_only is True

def test_the_penalty_counts_double_for_an_objective_lost_undetected_since_the_lesson_started(client):
    session = opened("f5", lessons=[{"id": "f5", "started_at": timezone.now().isoformat()}])
    Objective.objects.create(session=session, key="board-auth-user-partial", name="partial", difficulty=2,
                             achieved_at=timezone.now() - timedelta(minutes=1))
    with patch("range.docker.Docker.runner", Stand().runner()), patch("api.views.harness.fire", attacker({})[0]):
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
    assert logged["reason"] == ["lesson.check.replay_benign", []], "an ordinary sort the WAF logged is no fix"

def test_loot_from_the_dump_is_judged_by_the_board_s_own_accounts(client):
    session = opened("f6")
    kali_run(session, "f6", "dump", "kali-run")
    forged = DUMPED.replace("jiwoo    | pbkdf2_sha256$260000$q", "jiwoo    | pbkdf2_sha256$260000$X")
    with quietly():
        handed = step(client, session, "loot", body={"answer": forged}).json()

    assert handed["passed"] is True and handed["loot"]["matched"] == ["admin", "minseo"]

@pytest.mark.parametrize("check, reason", [
    ({"kind": "answer", "of": "status"}, "read from the record"),
    ({"kind": "answer", "of": "sqlmap_found", "about": "one"}, "read from the record"),
    ({"kind": "answer", "of": "rule", "marker": "step:one"}, "read from the record"),
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
    settings.FSL_SOURCE = str(tmp_path)

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
