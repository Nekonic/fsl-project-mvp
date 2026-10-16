import json
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
    return {"id": request_id, "at": time.time(), "method": "GET", "url": f"http://board.com{url}",
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

def test_no_foundation_question_carries_a_fixed_answer():
    for taught in wargames.foundations("board"):
        for shown in taught["steps"]:
            check = shown["check"]
            if check["kind"] in ("answer", "choice"):
                assert "accept" not in check and check.get("of"), (taught["id"], shown["id"])

@pytest.mark.parametrize("flavor, entry, logs, segment, wrong", [
    ("docker", "waf", "log-server", "sw1", "firewall"),
    ("openstack", "firewall", "log-server", "sw2", "waf"),
])
def test_the_range_questions_are_judged_against_the_substrate_s_own_topology(client, flavor, entry, logs, segment, wrong):
    session = opened("f1")
    with override_settings(FSL_TOPOLOGY=TOPOLOGIES[flavor], RANGE=declared.read(flavor=flavor)):
        answers = {name: step(client, session, name, body={"answer": given}).json()["passed"]
                   for name, given in (("entry", wrong), ("logs", logs), ("segment", segment))}
        answers["entry_right"] = step(client, session, "entry", body={"answer": entry}).json()["passed"]

    assert answers == {"entry": False, "logs": True, "segment": True, "entry_right": True}

@pytest.mark.parametrize("lesson_id, step_id, url, status, right, wrong", [
    ("f2", "status", KOREAN, 403, "403", "200"),
    ("f3", "meaning", KOREAN, 200, "2xx", "4xx"),
    ("f5", "stopped", "/search/?q=%27+OR+1%3D1--", 403, "WAF", "board.com"),
])
def test_a_question_is_judged_from_the_learner_s_own_website_pane_request(client, lesson_id, step_id, url, status,
                                                                          right, wrong):
    session = opened(lesson_id)
    before = step(client, session, step_id, body={"answer": right}).json()
    with patch.object(site, "kept", return_value=[browsed(url, status)]):
        judged = {given: step(client, session, step_id, body={"answer": given}).json()["passed"]
                  for given in (right, wrong)}

    assert (before["passed"], before["reason"]) == (False, ["lesson.check.unrecorded", []])
    assert judged == {right: True, wrong: False}

def test_every_control_a_foundation_points_at_is_on_the_blue_console(client):
    page = client.get("/blue/1/").content.decode()
    pointed = {step["point"]["panel"] for taught in wargames.foundations("board") for step in taught["steps"]
               if "panel" in step.get("point", {})}

    assert pointed and [panel for panel in pointed if panel.startswith("#") and f'id="{panel[1:]}"' not in page] == []

def test_the_kali_step_labels_its_command_and_passes_on_the_sensor_s_records_of_that_label(client):
    session = opened("f5")
    step(client, session, "sqlmap", tail="", body={"state": "reached"})
    marker = Session.objects.get(pk=session.pk).lesson_steps["sqlmap"]["marker"]
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}
    with indexed(http_event("another", "/?sort=x", 403, agent=SQLMAP_AGENT)):
        early = step(client, session, "sqlmap").json()
    run = [http_event(marker, f"/?sort=posts_post.id{n}", 403, host="fsl-edge", agent=SQLMAP_AGENT) for n in range(40)]
    alert = dict(run[0], event_type="alert", alert={"signature": "FSL SQLi attempt", "signature_id": 9000001})
    with indexed(*run, alert):
        ran = step(client, session, "sqlmap").json()

    assert f"'--headers=X-FSL-Case: {marker}'" in shown["sqlmap"]["command"]
    assert early["passed"] is False
    assert ran["passed"] is True and ran["kali"]["requests"] == 40
    recorded = Case.objects.get(session=session, case_id=marker)
    assert recorded.malicious and recorded.meta["kali"] == "sqlmap", "the learner's own red action, scored like any other"
    assert not any(recorded.meta.get(mark) for mark in ("seed", "verify", "check", "replay"))
    assert Detection.objects.filter(session=session, marker=marker).count() == 1, (
        "the run's alerts are read when it is recorded, so the first score knows it was noticed")

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

def test_a_passed_kali_step_stays_with_its_count_until_next_since_the_following_step_asks_for_it(client):
    from api import views

    steps = [views._shown_step(None, {key: value for key, value in step.items() if key != "query"})
             for step in wargames.lesson("board", lesson_id="f5")["steps"]]
    setup = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
localStorage.setItem('fsl-lesson-step-1', '4');
const progress = {sqlmap: {reached: "now", hint: 0, done_for_me: false}};
browser.element('pane-frame').getBoundingClientRect = () => ({left: 200, top: 50, right: 1000, bottom: 650, width: 800, height: 600});
Object.defineProperty(browser.element('coach-pop'), 'offsetHeight',
  {get: () => 300 + 400 * browser.element('coach-pop').querySelectorAll('[data-kali]').length});
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: true, hints: [], progress, ended_at: null, discover: "/kibana/",
                   site: {port: 8002, path: "/site/1/board.com/"}, waf_rules: "/etc/modsecurity.d/owasp-crs/rules",
                   lesson: {text: "lesson.attack", group: "foundations", cases: ["board-normal-search"], steps: STEPS,
                            theory: [{id: "attack", shows: "stopped"}], hints: ["why_total", "why_count"]}}};
  }
  if (request.route === "/api/sessions/1/lesson/steps/sqlmap/check/") {
    return {body: {passed: true, reason: null, hint: 0, hints: [], progress: {sqlmap: {reached: "now", passed: "now", hint: 0}},
                   kali: {name: "board-sqli-orderby-sqlmap", requests: 1896, sensors: {"fsl-edge": 1896}, discover: "/kibana/x"}}};
  }
  if (request.route.includes("/lesson/steps/")) return {body: {hint: 0, hints: [], progress}};
  return {status: 404, body: {detail: "not served"}};
});
""".replace("STEPS", json.dumps(steps))
    seen = open_page(client, "/blue/1/", setup=setup, scenario="""
      await browser.wait(100);
      await browser.click('[data-act="kali"]');
      await browser.wait(3000);
      const pop = browser.element('coach-pop');
      return {count: browser.text('coach-pop-count'), row: browser.text('[data-kali]'),
              next: !browser.element('coach-pop-next').disabled, bottom: parseFloat(pop.style.top) + pop.offsetHeight};
    """)

    assert seen["errors"] == []
    assert seen["result"]["count"] == "4 / 5", "the requests step asks for the count this row shows"
    assert "1896" in seen["result"]["row"] and seen["result"]["next"] is True
    assert seen["result"]["bottom"] <= 900 - 12, "the row made the popover taller; Next must stay on screen"
