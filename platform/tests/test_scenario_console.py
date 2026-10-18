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

def serving(state, items=ITEMS, lesson=None):
    return f"""
const range = {{state: {js(state)}, items: {js(items)}, posted: [], hinted: 0, windowed: 0, steps: []}};
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
  if (request.route === "/api/sessions/1/triage/" && request.method === "POST") {{
    range.posted.push(request.body);
    const right = request.body.item === "a1" ? request.body.verdict === "customer"
      : request.body.verdict === "attack" && request.body.succeeded === false;
    return {{body: {{item: request.body.item, right, verdict_right: right || request.body.verdict === "attack",
      succeeded_right: request.body.verdict === "attack" ? right : null, tries: 1, right_so_far: right ? 1 : 0}}}};
  }}
  if (request.route === "/api/sessions/1/triage/") return {{body: {{items: range.items, total: range.items.length, judged: 0}}}};
  if (request.route === "/api/sessions/1/ingest/") return {{body: {{ingested: 0}}}};
  if (request.route.startsWith("/api/sessions/1/lesson/steps/")) {{
    range.steps.push(request.route);
    const passed = request.route.endsWith("/check/");
    return {{body: {{passed, reason: null, progress: passed ? {{[request.route.split("/")[6]]: {{passed: true}}}} : {{}}}}}};
  }}
  return {{status: 404, body: {{detail: "not served"}}}};
}});
"""

def test_a_hint_offered_when_stuck_is_recorded_only_when_opened(client):
    offered = status(hints={"offer": {"reason": "idle", "about": "", "at": "x"}, "opened": [], "left": 4})
    seen = open_page(client, "/blue/1/", setup=serving(offered), scenario="""
      await browser.click('briefing-start');
      const before = browser.requests.filter((r) => r.route.endsWith('/scenario/hints/')).length;
      await browser.click('scenario-offer');
      return {before, after: browser.requests.filter((r) => r.route.endsWith('/scenario/hints/')).length};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"before": 0, "after": 1}

def test_the_judge_pane_lists_the_evidence_without_the_answer_and_posts_a_verdict_with_whether_it_got_in(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1")), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      const listed = browser.text('triage-list');
      await browser.click('[data-item="a1"] [data-judge="customer"]');
      await browser.click('[data-item="b2"] [data-judge="attack"]');
      await browser.click('[data-item="b2"] [data-succeeded="false"]');
      return {listed, posted: range.posted};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert "/search/?q=%3Cb%3E" in result["listed"]
    for label in ("attack", "customer", "malicious", "board-sqli"):
        assert label not in result["listed"].lower().replace(english("triage.attack").lower(), "").replace(
            english("triage.customer").lower(), "")
    assert result["posted"] == [{"item": "a1", "verdict": "customer"},
                                {"item": "b2", "verdict": "attack", "succeeded": False}]

def test_a_judgement_scenario_that_asks_the_kind_posts_it_with_the_verdict(client):
    card = wargames.scenario_card(wargames.scenario_run("1.3"))
    seen = open_page(client, "/blue/1/", setup=serving(status(card, id="1.3", cards=[])), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      await browser.click('[data-item="b2"] [data-judge="attack"]');
      await browser.click('[data-item="b2"] [data-pattern="CAPEC-66"]');
      await browser.click('[data-item="b2"] [data-succeeded="false"]');
      return range.posted;
    """)

    assert seen["errors"] == []
    assert seen["result"] == [{"item": "b2", "verdict": "attack", "succeeded": False, "pattern": "CAPEC-66"}]


LAID_OUT = """
const RECTS = new Map();
Object.getPrototypeOf(document.body).getBoundingClientRect = function () {
  return RECTS.get(this) || {left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0};
};
const box = (left, top, width, height) => ({left, top, width, height, right: left + width, bottom: top + height});
RECTS.set(browser.element('pane'), box(60, 56, 980, 744));
RECTS.set(browser.element('pane-body'), box(60, 100, 980, 700));
RECTS.set(document.querySelector('.pane-tab[data-pane="triage"]'), box(8, 300, 44, 44));
"""

def test_a_stepped_scenario_rings_the_rail_button_its_first_step_names_and_moves_on_when_it_is_pressed(client):
    lesson = wargames.lesson("board", lesson_id="1.1")
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1"), lesson=lesson) + LAID_OUT, scenario="""
      await browser.click('briefing-start');
      await browser.wait(0);
      await browser.wait(0);
      const first = {title: browser.text('step-title'), ring: !browser.element('coach-ring').classList.contains('hidden'),
                     left: browser.element('coach-ring').style.left, note: !browser.element('lesson').classList.contains('hidden')};
      await browser.click('[data-pane="triage"]');
      await browser.wait(0);
      await browser.wait(1600);
      const stayed = {title: browser.text('step-title'), next: browser.element('step-next').classList.contains('btn-blue')};
      await browser.click('step-next');
      await browser.wait(0);
      return {first, stayed, next: browser.text('step-title'), checked: range.steps.filter((route) => route.endsWith('/check/'))};
    """)
    result = seen["result"]
    steps = [step["id"] for step in lesson["steps"]]

    assert seen["errors"] == []
    assert result["first"] == {"title": english(f"{lesson['text']}.label.{steps[0]}"), "ring": True, "left": "2px", "note": True}
    assert result["checked"] == [f"/api/sessions/1/lesson/steps/{steps[0]}/check/"]
    assert result["stayed"] == {"title": english(f"{lesson['text']}.label.{steps[0]}"), "next": True}
    assert result["next"] == english(f"{lesson['text']}.label.{steps[1]}")
