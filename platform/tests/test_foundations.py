import json
import re
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from django.test import override_settings
from django.utils import timezone

import lesson
import topology
import wargames
from api import site
from api.models import Case, Detection, Session
from range import declared
from tests.browser import open_page
from tests.test_lesson_api import DUMPED, TRUTH
from tests.test_scenario_discovery import A_SCENARIO
from tests.test_strings import tables

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGIES = {flavor: ROOT / "deploy" / "topology" / f"range-{flavor}.gns3" for flavor in ("docker", "openstack")}
KOREAN = "/search/?q=%EC%84%9C%EC%9A%B8+%EB%A7%9B%EC%A7%91"
SQLMAP_AGENT = "sqlmap/1.8.4#stable (https://sqlmap.org)"

def opened(lesson_id, **fields):
    defense = wargames.lesson_defense("board", lesson_id)
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), guidance=True, lesson=lesson_id,
                                  defense=defense, **fields)

def step(client, session, step_id, tail="check/", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def browsed(url, status, request_id=1, ms=40):
    return {"id": request_id, "at": time.time(), "method": "GET", "url": f"http://board.com{url}", "to": "10.31.0.44",
            "status": status, "blocked": status == 403, "ms": ms}

def http_event(marker, url, status, host="fsl-wargame-host", agent="Mozilla/5.0", **fields):
    return {"fsl_source": "suricata", "event_type": "http", "timestamp": timezone.now().isoformat(),
            "src_ip": fields.get("src_ip", "10.30.0.102"), "dest_ip": fields.get("dest_ip", "10.30.0.63"),
            "dest_port": fields.get("dest_port", 8000), "log": {"syslog": {"hostname": host}},
            "http": {"url": url, "status": status, "http_method": "GET", "http_user_agent": agent,
                     "request_headers": [{"name": "X-FSL-Case", "value": marker}] if marker else []}}

def indexed(*events):
    return patch("api.views._fetched", lambda index, start, end, newest_first: (
        [(f"doc-{position}", event) for position, event in enumerate(events)], None))

def quietly():
    return patch("api.views._ingest", lambda session, within=None: {})

def test_the_foundations_come_first_on_the_home_card_with_what_each_teaches_and_open_as_lessons(client):
    from tests.test_lesson_path import sensed

    board = {w["id"]: w for w in client.get("/api/wargames/").json()}["board"]
    fire, fired = sensed({})
    with patch("api.views.harness.fire", fire):
        started = client.post_json("/api/sessions/", {"scenario": "board", "lesson": "f6"}).json()

    assert [card["id"] for card in board["foundations"]] == ["f1", "f2", "f3", "f4", "f5", "f6"]
    assert all(card["learns"] == f"{card['title'].rsplit('.', 1)[0]}.learns" and card["minutes"]
               for card in board["foundations"])
    assert (started["lesson_id"], started["defense"]) == ("f6", "missed")
    assert fired == ["board-normal-search"], "only the benign case is seeded; the learner runs sqlmap"

def test_every_foundation_has_its_words_and_withheld_answers_in_both_languages():
    from console import strings

    table, withheld = tables(), strings.withheld()
    for taught in wargames.foundations("board"):
        prefix = taught["text"]
        keys = [f"{prefix}.{part}" for part in ("title", "summary", "learns", "read", "write", "replay", "verify")]
        keys += [f"{prefix}.theory.{card['id']}.{part}" for card in taught["theory"] for part in ("title", "body")]
        keys += [f"{prefix}.hint.{hint}.{part}" for hint in taught["hints"] for part in ("title", "body")]
        for shown in taught["steps"]:
            check = shown["check"]
            keys += [f"{prefix}.{part}.{shown['id']}" for part in ("label", "coach", "nudge", "ok")]
            keys += [f"{prefix}.option.{shown['id']}.{option}" for option in check.get("options", [])]
            keys += [f"{prefix}.wrong.{shown['id']}.{known}" for known in check.get("known", [])]
            keys += [f"{prefix}.fail.{shown['id']}"] if check["kind"] in ("sent", "kali", "loot") else []
            keys += [f"{prefix}.chip.{shown['id']}"] if shown.get("query") else []
            keys += [f"{prefix}.does.{shown['id']}"] if check["kind"] == "kali" or shown.get("command") else []
            held = [f"{prefix}.{part}.{shown['id']}" for part in ("answer", "line")]
            for language in ("en", "ko"):
                assert not [key for key in held if key not in withheld[language]], (taught["id"], language)
        for language in ("en", "ko"):
            assert not [key for key in keys if key not in table[language]], (taught["id"], language)
        body = table["en"][f"{prefix}.theory.{taught['theory'][0]['id']}.body"]
        assert len(body.split()) <= 250, (taught["id"], len(body.split()))

def test_no_foundation_question_carries_a_fixed_answer():
    for taught in wargames.foundations("board"):
        for shown in taught["steps"]:
            check = shown["check"]
            if check["kind"] in ("answer", "choice"):
                assert "accept" not in check and check.get("of"), (taught["id"], shown["id"])

@pytest.mark.parametrize("flavor, entry, logs, segment, wrong", [
    ("docker", "fsl-waf", "fsl-elasticsearch", "estate", "fsl-edge"),
    ("openstack", "fsl-edge", "fsl-elasticsearch", "board-default", "fsl-waf"),
])
def test_the_range_questions_are_judged_against_the_substrate_s_own_topology(client, flavor, entry, logs, segment, wrong):
    session = opened("f1")
    with override_settings(FSL_TOPOLOGY=TOPOLOGIES[flavor], RANGE=declared.read(flavor=flavor)):
        answers = {name: step(client, session, name, body={"answer": given}).json()["passed"]
                   for name, given in (("entry", wrong), ("logs", logs), ("segment", segment))}
        answers["entry_right"] = step(client, session, "entry", body={"answer": entry}).json()["passed"]

    assert answers == {"entry": False, "logs": True, "segment": True, "entry_right": True}

def test_a_request_question_is_answered_from_the_learner_s_own_website_pane_request(client):
    session = opened("f3")
    before = step(client, session, "method", body={"answer": "GET"}).json()
    with patch.object(site, "kept", return_value=[browsed(KOREAN, 200)]):
        sent = step(client, session, "search").json()
        answers = {name: step(client, session, name, body={"answer": given}).json()["passed"]
                   for name, given in (("method", "get"), ("path", "/search/"), ("parameter", "q"),
                                       ("meaning", "2xx"))}
        wrong = step(client, session, "meaning", body={"answer": "4xx"}).json()["passed"]

    assert before["reason"] == ["lesson.check.unrecorded", []], "nothing to read before the learner sends a request"
    assert sent["passed"] is True
    assert answers == {"method": True, "path": True, "parameter": True, "meaning": True}
    assert wrong is False

def test_the_status_question_follows_whatever_the_learner_s_own_request_got(client):
    session = opened("f2")
    with patch.object(site, "kept", return_value=[browsed(KOREAN, 403)]):
        served = step(client, session, "status", body={"answer": "200"}).json()["passed"]
        blocked = step(client, session, "status", body={"answer": "403"}).json()["passed"]

    assert (served, blocked) == (False, True)

def test_the_kali_step_labels_its_command_and_passes_on_the_sensor_s_records_of_that_label(client):
    session = opened("f5")
    reached = step(client, session, "sqlmap", tail="", body={"state": "reached"}).json()
    marker = Session.objects.get(pk=session.pk).lesson_steps["sqlmap"]["marker"]
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}
    with indexed(http_event("another", "/?sort=x", 403, agent=SQLMAP_AGENT)):
        early = step(client, session, "sqlmap").json()
    run = [http_event(marker, f"/?sort=posts_post.id{n}", 403, host="fsl-edge", agent=SQLMAP_AGENT) for n in range(40)]
    alert = dict(run[0], event_type="alert", alert={"signature": "FSL SQLi attempt", "signature_id": 9000001})
    with indexed(*run, alert):
        ran = step(client, session, "sqlmap").json()
        close = step(client, session, "requests", body={"answer": "38"}).json()["passed"]
        far = step(client, session, "requests", body={"answer": "20"}).json()["passed"]

    assert reached["progress"]["sqlmap"]["command"] == shown["sqlmap"]["command"]
    assert shown["sqlmap"]["command"].startswith("sqlmap -u 'http://board.com/?sort=posts_post.id*'")
    assert f"'--headers=X-FSL-Case: {marker}'" in shown["sqlmap"]["command"]
    assert early["passed"] is False and early["reason"] == ["lesson.check.kali_none", ["sqlmap"]]
    assert ran["passed"] is True and ran["kali"]["requests"] == 40
    assert "modsecurity" not in ran["kali"]["discover"], "the Kibana link shows the http records, not only alerts"
    recorded = Case.objects.get(session=session, case_id=marker)
    assert recorded.malicious and recorded.meta["kali"] == "sqlmap", "the learner's own red action, scored like any other"
    assert not any(recorded.meta.get(mark) for mark in ("seed", "verify", "check", "replay"))
    assert Detection.objects.filter(session=session, marker=marker).count() == 1, (
        "the run's alerts are read when it is recorded, so the first score knows it was noticed")
    assert (close, far) == (True, False), "a count within 10% of the record passes"

def test_what_leaked_is_judged_by_the_board_s_own_accounts_and_counts_in_the_first_score(client):
    session = opened("f6")
    marker = "kali-run"
    Session.objects.filter(pk=session.pk).update(lesson_steps={"sqlmap": {"marker": marker, "passed": "x"}})
    Case.objects.create(session=session, case_id=marker, name="board-sqli-orderby-sqlmap", malicious=True,
                        correlation="marker", started_at=timezone.now() - timedelta(minutes=3),
                        ended_at=timezone.now(), meta={"kali": "sqlmap"})
    Detection.objects.create(session=session, detection_id="s1", source="suricata", signature="FSL SQLi attempt",
                             timestamp=timezone.now(), marker=marker, raw={})
    session.refresh_from_db()
    forged = DUMPED.replace("jiwoo    | pbkdf2_sha256$260000$q", "jiwoo    | pbkdf2_sha256$260000$X")
    with quietly():
        handed = step(client, session, "loot", body={"answer": forged}).json()
        counts = {given: step(client, session, "leaked", body={"answer": given}).json()["passed"] for given in ("3", "2")}
        lost = client.get(f"/api/sessions/{session.pk}/").json()["result"]["objectives"]
        answered = step(client, session, "lost", body={"answer": str(lost["lost"])}).json()["passed"]

    assert handed["passed"] is True and handed["loot"]["matched"] == ["admin", "minseo"]
    assert counts == {"3": False, "2": True}, "a hash that does not match the snapshot is not a leak"
    assert lost["lost"] == 2 and lost["undetected"] == 0, "partial and admin; not all accounts"
    assert answered is True

def test_the_missed_posture_turns_off_the_blocking_rules_and_the_question_reads_the_waf_itself(client):
    session = opened("f6")
    standing = {"paranoia": 1, "exclusions": [{"rule_id": 949110, "target": "", "path": ""},
                                              {"rule_id": 959100, "target": "", "path": ""}]}
    with patch("api.views._waf_in_force", return_value=standing):
        answers = {given: step(client, session, "excluded", body={"answer": given}).json()["passed"]
                   for given in ("949110", "959100", "942100")}

    assert wargames.defense("board", "missed")["waf"]["exclusions"] == [{"rule_id": 949110}, {"rule_id": 959100}]
    assert answers == {"949110": True, "959100": True, "942100": False}

@pytest.mark.parametrize("check, reason", [
    ({"kind": "answer", "of": "status"}, "read from the record"),
    ({"kind": "answer", "of": "requests", "about": "one"}, "read from the record"),
    ({"kind": "sent", "match": "("}, "match"),
    ({"kind": "loot", "about": "one"}, "about"),
    ({"kind": "kali", "case": "no-such-case"}, "tool case"),
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

def test_the_range_facts_come_from_the_project_and_the_declaration():
    stack = declared.read(flavor="openstack")
    project = json.loads(TOPOLOGIES["openstack"].read_text())

    assert topology.facts(project, stack, "corp") == {
        "entry": ["fsl-edge"], "logs": ["fsl-elasticsearch"], "segment": ["corp-default"]}

def test_a_pasted_table_or_plain_pairs_are_read_as_loot():
    assert lesson.pasted_rows("admin:hash-a\n| jiwoo | hash-b |", []) == [("admin", "hash-a"), ("jiwoo", "hash-b")]
    assert lesson.within(100, 0.1)[0] == 100 and set(lesson.within(100, 0.1)) == set(range(90, 111))
    assert lesson.within(0, 0.1) == []

def test_a_kibana_link_over_every_record_drops_the_alerts_only_query():
    import kibana

    start = timezone.now()
    narrowed = kibana.discover_path("fsl-logs-1-*", start, None, 'event_type : "http"', everything=True)
    alerts = kibana.discover_path("fsl-logs-1-*", start, None, 'event_type : "http"')

    assert "fsl_source" not in re.sub(r"%[0-9A-F]{2}", " ", narrowed.split("query:")[-1])
    assert "fsl_source" in re.sub(r"%[0-9A-F]{2}", " ", alerts.split("query:")[-1])

FOUNDED = """
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [
      {id: "board", name: "Board", description: "", cases: 1,
       foundations: [{id: "f1", order: 1, title: "lesson.range.title", goal: "lesson.range.summary",
                      learns: "lesson.range.learns", minutes: 10, level: "easy", defense: "full",
                      prerequisites: [], steps: 4}]},
    ]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 9}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_the_home_page_lists_the_foundations_and_starts_one_guided(client):
    seen = open_page(client, "/", setup=FOUNDED, scenario="""
      const order = [...document.querySelectorAll('[data-foundation], [data-lesson-card]')]
        .map((found) => found.dataset.foundation || found.dataset.lessonCard);
      await browser.click('[data-lesson-id="f1"]');
      return {order, posted: browser.requests.filter((r) => r.method === 'POST' && r.route === '/api/sessions/')
        .map((r) => r.body)};
    """)

    assert seen["errors"] == []
    assert seen["result"]["order"] == ["f1"], "no older lesson card is left beside the foundations"
    assert seen["result"]["posted"] == [{"scenario": "board", "guidance": True, "lesson": "f1", "defense": "full"}]

def test_the_kali_step_offers_its_command_for_the_red_console_and_shows_what_the_sensor_counted(client):
    from api import views
    from tests.browser import english

    steps = [views._shown_step(None, step) for step in wargames.lesson("board", lesson_id="f5")["steps"]]
    command = "sqlmap -u 'http://board.com/?sort=posts_post.id*' '--headers=X-FSL-Case: m-1'"
    setup = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
localStorage.setItem('fsl-lesson-step-1', '5');
const progress = {sqlmap: {reached: "now", hint: 0, done_for_me: false, command: COMMAND}};
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: true, hints: [], progress, ended_at: null, discover: "/kibana/",
                   site: {port: 8002, path: "/site/1/board.com/"}, waf_rules: "/etc/modsecurity.d/owasp-crs/rules",
                   lesson: {text: "lesson.attack", group: "foundations", cases: ["board-normal-search"],
                            steps: STEPS.map((step) => step.id === "sqlmap" ? {...step, command: COMMAND} : step),
                            theory: [{id: "attack", shows: "stopped"}], hints: ["why_total", "why_count"]}}};
  }
  if (request.route === "/api/sessions/1/lesson/steps/sqlmap/check/") {
    return {body: {passed: false, reason: ["lesson.check.kali_none", ["sqlmap"]], hint: 0, hints: [], progress,
                   kali: {name: "board-sqli-orderby-sqlmap", requests: 12, sensors: {"fsl-edge": 12}, discover: "/kibana/x"}}};
  }
  if (request.route.includes("/lesson/steps/")) return {body: {hint: 0, hints: [], progress}};
  return {status: 404, body: {detail: "not served"}};
});
""".replace("COMMAND", json.dumps(command)).replace("STEPS", json.dumps(steps))
    seen = open_page(client, "/blue/1/", setup=setup, scenario="""
      const run = document.getElementById('coach-pop-run').classList.contains('hidden');
      const typed = browser.text('coach-pop-typed');
      await browser.click('[data-act="kali"]');
      return {run, typed, code: browser.text('coach-pop-code'), row: browser.text('[data-kali]'),
              posted: browser.requests.filter((r) => r.route.endsWith('/sqlmap/check/')).length};
    """)

    assert seen["errors"] == []
    assert seen["result"]["run"] is True, "the WAF terminal's Run button would paste sqlmap into the wrong box"
    assert seen["result"]["typed"] == english("lesson.kali.where")
    assert seen["result"]["code"] == command
    assert english("lesson.kali.requests", 12) in seen["result"]["row"] and seen["result"]["posted"] == 1
