from json import dumps as js

import pytest

import wargames
from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

CARD = wargames.scenario_card(wargames.scenario_run("2.1"))
JUDGEMENT = wargames.scenario_card(wargames.scenario_run("1.1"))

def status(card=CARD, **changed):
    return {
        **card, "phase": "running", "opened_at": "2026-10-13T06:00:00+00:00", "ends_at": "2026-10-13T06:20:00+00:00",
        "window_at": "2026-10-13T06:16:00+00:00", "time_left": 754,
        "live": {"customers_blocked_per_minute": 12, "alerted_per_minute": 31, "objectives_lost": 0,
                 "customers": {"sent": 90, "served": 70, "blocked": 20}},
        "window": None, "windows": 0, "completion": {"state": "pending", "reasons": [], "fix": None},
        "cards": ["blocked"], "text": "scenario.korean" if card is CARD else "scenario.shift",
        "hints": {"offer": None, "opened": [], "left": 4}, "traffic": {"running": True, "error": ""},
        **changed,
    }

ITEMS = [
    {"item": "a1", "first": "2026-10-13T06:02:00+00:00", "last": "2026-10-13T06:02:00+00:00", "alerts": 2,
     "sources": ["175.192.0.10"], "request": {"method": "GET", "path": "/search/?q=%3Cb%3E"}, "waf": "blocked",
     "status": 403, "rules": [{"engine": "modsecurity", "rule": "941320", "signature": "XSS", "count": 1}]},
    {"item": "b2", "first": "2026-10-13T06:03:00+00:00", "last": "2026-10-13T06:04:00+00:00", "alerts": 900,
     "sources": ["5.188.10.10"], "request": {"method": "GET", "path": "/?sort=posts_post.id"}, "waf": "blocked",
     "status": 403, "rules": [{"engine": "suricata", "rule": "9000001", "signature": "FSL SQLi", "count": 400}]},
]

DEBRIEF = {
    "scenario": "2.1", "title": "scenario.korean.title", "task_class": "availability",
    "overview": {"passed": False, "verified": 1, "mode": "guided", "fix": "rule", "reasons": [],
                 "steps": {"passed": 0, "total": 0}, "help": {"hints": 1, "skipped": 0, "done_for_me": 0}},
    "evidence": [], "change": {"before": {"paranoia": 3, "exclusions": []}, "after": {"paranoia": 3, "exclusions": [
        {"rule_id": 949110, "target": "", "path": ""}]}, "added": [], "removed": [], "diff": ["+SecAction 949110"]},
    "cases": [{"name": "board-sqli-orderby-sqlmap", "malicious": True, "before": "held", "after": "leaked"}],
    "risk": [["scenario.risk.rule", []]],
    "customers": {"sent": 800, "served": 700, "blocked": 100, "in_window": [0],
                  "blocked_actions": {"search-korean": 80}},
    "timeline": [
        {"n": 0, "case": "board-sqli-orderby-sqlmap", "origin": "ru", "state": "fired", "in_window": False,
         "outcome": "held", "leaked": [], "at": 240, "detected": True, "error": ""},
        {"n": 1, "case": "board-sqli-orderby-sqlmap", "origin": "ru", "state": "fired", "in_window": True,
         "outcome": "leaked", "leaked": ["admin", "jiwoo"], "at": 480, "detected": True, "error": ""},
    ],
    "triage": {"right": 0, "first_try": 0, "judged": 0, "items": 0},
    "at": {"opened": "2026-10-13T06:00:00+00:00", "verified": "2026-10-13T06:12:00+00:00"},
}

def serving(state, items=ITEMS, lesson=None):
    return f"""
const range = {{state: {js(state)}, items: {js(items)}, posted: [], hinted: 0, windowed: 0}};
browser.serve((request) => {{
  if (request.route === "/api/sessions/1/") return {{body: {{id: 1, scenario: "board", course_scenario: range.state.id,
    kind: "scenario", ended_at: null, guidance: Boolean({js(lesson)}), mode: "guided", lesson: {js(lesson)},
    hints: [], progress: {{}}, discover: "/kibana/app/discover#/", waf_box: "fsl-1-waf", waf_rules: "/etc"}}}};
  if (request.route === "/api/sessions/1/scenario/") return {{body: range.state}};
  if (request.route === "/api/sessions/1/scenario/verify-window/") {{
    range.windowed += 1;
    range.state = {{...range.state, phase: "window", time_left: 240}};
    return {{status: 201, body: range.state}};
  }}
  if (request.route === "/api/sessions/1/scenario/hints/") {{
    range.hinted += 1;
    range.state = {{...range.state, hints: {{offer: null, opened: ["find"], left: 3}}}};
    return {{status: 201, body: {{hint: "find", text: "scenario.korean.hint.find", reason: "idle", ...range.state.hints}}}};
  }}
  if (request.route === "/api/sessions/1/scenario/debrief/") return {{body: {js(DEBRIEF)}}};
  if (request.route === "/api/sessions/1/triage/" && request.method === "POST") {{
    range.posted.push(request.body);
    const right = request.body.item === "a1" ? request.body.verdict === "customer"
      : request.body.verdict === "attack" && request.body.succeeded === false;
    return {{body: {{item: request.body.item, right, verdict_right: right || request.body.verdict === "attack",
      succeeded_right: request.body.verdict === "attack" ? right : null, tries: 1, right_so_far: right ? 1 : 0}}}};
  }}
  if (request.route === "/api/sessions/1/triage/") return {{body: {{items: range.items, total: range.items.length, judged: 0}}}};
  if (request.route === "/api/sessions/1/ingest/") return {{body: {{ingested: 0}}}};
  return {{status: 404, body: {{detail: "not served"}}}};
}});
"""

def test_a_scenario_opens_on_its_briefing_and_the_range_behind_it_keeps_its_live_strip(client):
    seen = open_page(client, "/blue/1/", setup=serving(status()), scenario="""
      const shown = !browser.element('briefing').classList.contains('hidden');
      const briefing = {situation: browser.text('briefing-situation'), goal: browser.text('briefing-goal'),
                        measured: browser.text('briefing-measured'), time: browser.text('briefing-time')};
      await browser.click('briefing-start');
      return {shown, briefing, hidden: browser.element('briefing').classList.contains('hidden'),
              strip: browser.element('scenario-strip').classList.contains('flex'),
              left: browser.text('scenario-left'), blocked: browser.text('scenario-blocked'),
              alerts: browser.text('scenario-alerts'), lost: browser.text('scenario-lost'),
              judge: browser.element('[data-pane="triage"]').classList.contains('hidden'),
              card: browser.element('scenario-cards').textContent};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["shown"] and result["hidden"]
    assert result["briefing"] == {
        "situation": english("scenario.korean.situation"), "goal": english("scenario.korean.goal"),
        "measured": english("scenario.korean.measured_by"),
        "time": english("scenario.briefing.time_line", 20, 4, "12:34"),
    }
    assert (result["left"], result["blocked"], result["alerts"], result["lost"]) == ("12:34", "12", "31", "0")
    assert result["judge"] is True, "an availability scenario has nothing to judge"
    assert english("scenario.korean.card.blocked.title") in result["card"]

def test_the_briefing_is_shown_once_and_reopens_from_the_strip(client):
    seen = open_page(client, "/blue/1/", setup="localStorage.setItem('fsl-scenario-briefed-1', 'true');" + serving(status()),
                     scenario="""
      const first = browser.element('briefing').classList.contains('hidden');
      await browser.click('scenario-briefing-open');
      return {first, again: !browser.element('briefing').classList.contains('hidden')};
    """)

    assert seen["result"] == {"first": True, "again": True}

def test_i_m_done_opens_the_final_check_and_the_strip_says_it_runs(client):
    seen = open_page(client, "/blue/1/", setup=serving(status()), scenario="""
      await browser.click('briefing-start');
      await browser.click('scenario-done');
      return {asked: browser.requests.filter((r) => r.route.endsWith('/scenario/verify-window/')).length,
              said: browser.text('scenario-done'), disabled: browser.element('scenario-done').disabled,
              phase: browser.text('scenario-phase')};
    """)

    assert seen["result"] == {"asked": 1, "said": english("scenario.done.checking"), "disabled": True,
                              "phase": english("scenario.phase.window")}

def test_a_hint_is_offered_when_stuck_and_recorded_only_when_opened(client):
    offered = status(hints={"offer": {"reason": "idle", "about": "", "at": "x"}, "opened": [], "left": 4})
    seen = open_page(client, "/blue/1/", setup=serving(offered), scenario="""
      await browser.click('briefing-start');
      const before = browser.requests.filter((r) => r.route.endsWith('/scenario/hints/')).length;
      const visible = !browser.element('scenario-offer').classList.contains('hidden');
      const why = browser.element('scenario-offer').title;
      await browser.click('scenario-offer');
      return {before, visible, why, after: browser.requests.filter((r) => r.route.endsWith('/scenario/hints/')).length,
              hint: browser.text('scenario-hint-list'),
              gone: browser.element('scenario-offer').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert (result["before"], result["visible"], result["after"], result["gone"]) == (0, True, 1, True)
    assert result["why"] == english("scenario.hint.why.idle")
    assert result["hint"] == english("scenario.korean.hint.find")

def test_the_judge_pane_lists_the_evidence_and_posts_a_verdict_with_whether_it_got_in(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1")), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      const listed = browser.text('triage-list');
      await browser.click('[data-item="a1"] [data-judge="customer"]');
      await browser.click('[data-item="b2"] [data-judge="attack"]');
      const asked = browser.element('[data-item="b2"] [data-got-in]').classList.contains('flex');
      await browser.click('[data-item="b2"] [data-succeeded="false"]');
      return {listed, asked, posted: range.posted,
              said: [browser.text('[data-item="a1"] [data-said]'), browser.text('[data-item="b2"] [data-said]')],
              shown: browser.element('[data-pane="triage"]').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["shown"] is False
    assert "/search/?q=%3Cb%3E" in result["listed"] and "941320" in result["listed"]
    assert english("triage.from", "5.188.10.10") in result["listed"]
    for label in ("attack", "customer", "malicious", "board-sqli"):
        assert label not in result["listed"].lower().replace(english("triage.attack").lower(), "").replace(
            english("triage.customer").lower(), "")
    assert result["asked"] is True
    assert result["posted"] == [{"item": "a1", "verdict": "customer"},
                                {"item": "b2", "verdict": "attack", "succeeded": False}]
    assert result["said"] == [english("triage.said.right"), english("triage.said.right")]

def test_the_debrief_opens_after_the_final_check_with_customers_and_the_attack_timeline(client):
    judged = status(phase="failed", windows=1, completion={
        "state": "failed", "reasons": [["scenario.fail.leaked", [1, 1]]], "fix": "rule"})
    seen = open_page(client, "/blue/1/", setup=serving(judged), scenario="""
      return {open: !browser.element('scenario-debrief').classList.contains('hidden'),
              verdict: browser.text('scenario-verdict'), body: browser.text('scenario-debrief-body'),
              rows: browser.element('scenario-debrief-body').querySelectorAll('[data-timeline]').length};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["open"] is True
    assert english("scenario.fail.leaked", 1, 1) in result["verdict"]
    assert english("lesson.fix.rule") in result["verdict"]
    assert english("scenario.debrief.customers.line", 800, 700, 100) in result["body"]
    assert english("scenario.debrief.customers.window", 0) in result["body"]
    assert result["rows"] == 2
    assert english("scenario.debrief.leaked", "admin, jiwoo") in result["body"]
    assert english("scenario.risk.rule") in result["body"]

def test_the_home_page_offers_each_scenario_and_starts_it_on_its_briefing(client):
    catalogue = [{"id": "board", "name": "Community board", "description": "", "public_url": "http://board.com",
                  "judged": True, "lesson": False, "model": "loot_verified", "cases": 1, "attacks": 1, "benign": 0,
                  "objectives": 3, "lessons": [], "foundations": [], "scenarios": [JUDGEMENT, CARD],
                  "category": "", "difficulty": "", "minutes": 40, "covers": [], "uncovered": []}]
    seen = open_page(client, "/", setup=f"""
browser.serve((request) => {{
  if (request.route === "/api/wargames/") return {{body: {js(catalogue)}}};
  if (request.route === "/api/sessions/" && request.method === "POST") return {{status: 201, body: {{id: 9}}}};
  if (request.route === "/api/sessions/") return {{body: []}};
  if (request.route === "/api/range/ready/") return {{body: {{ready: true, slots: [], slot: {{blocked: []}}}}}};
  return {{status: 404, body: {{detail: "not served"}}}};
}});
""", scenario="""
      const listed = browser.element('[data-scenarios="board"]').textContent;
      await browser.click('[data-course="2.1"]');
      await browser.wait(1000);
      return {listed, posted: browser.requests.filter((r) => r.route === '/api/sessions/' && r.method === 'POST')
              .map((r) => r.body), went: location.href};
    """)
    result = seen["result"]

    assert english("scenario.shift.title") in result["listed"] and english("scenario.korean.title") in result["listed"]
    assert english("scenario.class.availability") in result["listed"]
    assert english("scenario.guidance.worked") in result["listed"]
    assert english("scenario.korean.practise") in result["listed"]
    assert result["posted"] == [{"scenario": "2.1"}]
    assert result["went"].endswith("/blue/9/")

def test_a_worked_scenario_coaches_its_steps_and_polls_the_triage_checks(client):
    from api import views

    taught = wargames.lesson("board", lesson_id="1.1")
    lesson = {"id": "1.1", "text": taught["text"], "cases": [], "hints": taught["hints"], "verifies": False,
              "steps": [views._shown_step(None, step) for step in taught["steps"]]}
    setup = "localStorage.setItem('fsl-lesson-landed-1', 'true');" + serving(status(JUDGEMENT, id="1.1"), lesson=lesson)
    setup = setup.replace('if (request.route === "/api/sessions/1/ingest/")', '''if (request.route.includes("/lesson/steps/")) {
    range.checked = (range.checked || []).concat([request.route]);
    return {body: {passed: request.route.includes("/open/"), reason: null, hint: 0, hints: [], progress: {}}};
  }
  if (request.route === "/api/sessions/1/ingest/")''')
    seen = open_page(client, "/blue/1/", setup=setup, scenario="""
      Object.getPrototypeOf(document.body).getBoundingClientRect =
        () => ({left: 0, top: 0, right: 100, bottom: 30, width: 100, height: 30});
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      for (let i = 0; i < 12; i += 1) await browser.wait(1000);
      return {checked: range.checked || [], check: browser.element('#lesson-tabs [data-tab="check"]').classList.contains('hidden'),
              done: browser.text('lesson-done'), hints: browser.text('lesson-hints')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["check"] is True, "a scenario has no replay or VERIFY to offer"
    assert english("scenario.shift.goal") in result["done"]
    assert result["hints"] == "", "the scenario's hints are offered when stuck, not listed in the note"
    assert any("/lesson/steps/customer/check/" in route for route in result["checked"])

def test_cards_come_one_at_a_time_and_a_dismissed_card_stays_dismissed(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1", cards=["evidence", "alert"])), scenario="""
      await browser.click('briefing-start');
      const first = [...document.querySelectorAll('[data-card]')].map((card) => card.dataset.card);
      await browser.click('[data-card="evidence"] button');
      const second = [...document.querySelectorAll('[data-card]')].map((card) => card.dataset.card);
      await browser.wait(6000);
      return {first, second, after: [...document.querySelectorAll('[data-card]')].map((card) => card.dataset.card),
              kept: localStorage.getItem('fsl-scenario-cards-1')};
    """)

    assert seen["result"] == {"first": ["evidence"], "second": ["alert"], "after": ["alert"], "kept": '["evidence"]'}

def test_the_judge_pane_docks_the_cards_the_hints_and_the_coach_above_its_list_and_releases_them(client):
    from api import views

    taught = wargames.lesson("board", lesson_id="1.1")
    lesson = {"id": "1.1", "text": taught["text"], "cases": [], "hints": taught["hints"], "verifies": False,
              "steps": [views._shown_step(None, step) for step in taught["steps"]]}
    setup = "localStorage.setItem('fsl-lesson-landed-1', 'true');" + serving(
        status(JUDGEMENT, id="1.1", cards=["evidence"], hints={"offer": None, "opened": ["source"], "left": 2}),
        lesson=lesson)
    setup = setup.replace('if (request.route === "/api/sessions/1/ingest/")', '''if (request.route.includes("/lesson/steps/")) {
    return {body: {passed: request.route.includes("/open/"), reason: null, hint: 0, hints: [], progress: {}}};
  }
  if (request.route === "/api/sessions/1/ingest/")''')
    seen = open_page(client, "/blue/1/", setup=setup, scenario="""
      Object.getPrototypeOf(document.body).getBoundingClientRect =
        () => ({left: 0, top: 0, right: 100, bottom: 30, width: 100, height: 30});
      await browser.click('briefing-start');
      await browser.click('scenario-offer');
      const inDock = (id) => browser.element(id).parentNode === browser.element('triage-dock');
      const before = {cards: inDock('scenario-cards'), hints: inDock('scenario-hints')};
      await browser.click('[data-pane="triage"]');
      for (let i = 0; i < 4; i += 1) await browser.wait(1000);
      const docked = {cards: inDock('scenario-cards'), hints: inDock('scenario-hints'), coach: inDock('coach-pop'),
                      first: browser.element('triage-dock').children[0].id,
                      position: browser.element('scenario-cards').style.position};
      await browser.click('[data-pane="topology"]');
      const released = {cards: inDock('scenario-cards'), hints: inDock('scenario-hints'), coach: inDock('coach-pop'),
                        position: browser.element('scenario-cards').style.position};
      return {before, docked, released};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["before"] == {"cards": False, "hints": False}
    assert result["docked"] == {"cards": True, "hints": True, "coach": True, "first": "coach-pop", "position": "static"}
    assert result["released"] == {"cards": False, "hints": False, "coach": False, "position": ""}

def test_a_detection_scenario_opens_the_ids_rules_in_their_own_pane(client):
    card = wargames.scenario_card(wargames.scenario_run("3.2"))
    setup = serving(status(card, id="3.2", cards=[])).replace(
        'if (request.route === "/api/sessions/1/ingest/")',
        '''if (request.route === "/api/rules/") return {body: {content: "alert http any any -> any any (sid:1;)", version: "v1"}};
  if (request.route === "/api/sessions/1/ingest/")''')
    seen = open_page(client, "/blue/1/", setup=setup, scenario="""
      await browser.click('briefing-start');
      const tab = browser.element('[data-pane="rules"]');
      await browser.click('[data-pane="rules"]');
      return {hidden: tab.classList.contains('hidden'), inPane: browser.element('lesson-rules').parentNode.id,
              shown: browser.element('rules-pane').style.display, text: browser.element('lesson-rules-text').value,
              judge: browser.element('[data-pane="triage"]').classList.contains('hidden')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"hidden": False, "inPane": "rules-pane-body", "shown": "flex",
                              "text": "alert http any any -> any any (sid:1;)", "judge": True}

def test_a_judgement_scenario_that_asks_the_kind_posts_it_with_the_verdict(client):
    card = wargames.scenario_card(wargames.scenario_run("1.3"))
    seen = open_page(client, "/blue/1/", setup=serving(status(card, id="1.3", cards=[])), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      await browser.click('[data-item="b2"] [data-judge="attack"]');
      const asked = browser.element('[data-item="b2"] [data-kind-of]').classList.contains('flex');
      const before = browser.element('[data-item="b2"] [data-got-in]').classList.contains('flex');
      const kinds = [...document.querySelectorAll('[data-item="b2"] [data-pattern]')].map((button) => button.textContent);
      await browser.click('[data-item="b2"] [data-pattern="CAPEC-66"]');
      await browser.click('[data-item="b2"] [data-succeeded="false"]');
      return {asked, before, kinds, posted: range.posted};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert (result["asked"], result["before"]) == (True, False)
    assert result["kinds"] == [english(f"triage.pattern.{pattern}") for pattern in card["patterns"]]
    assert result["posted"] == [{"item": "b2", "verdict": "attack", "succeeded": False, "pattern": "CAPEC-66"}]
