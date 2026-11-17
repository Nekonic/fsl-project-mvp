from json import dumps as js

import pytest

import wargames
from tests.browser import open_page, worded

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
     "status": 403, "rules": [{"engine": "suricata", "rule": "9000001", "signature": "SQLi", "count": 400}]},
]

def serving(state, items=ITEMS, lesson=None):
    return f"""
const range = {{state: {js(state)}, items: {js(items)}, posted: [], hinted: 0, windowed: 0, steps: [], checks: [],
               passing: true, closed: 0}};
browser.serve((request) => {{
  if (request.route === "/api/sessions/1/") return {{body: {{id: 1, scenario: "board", course_scenario: range.state.id,
    kind: "scenario", ended_at: null, guidance: Boolean({js(lesson)}), mode: "guided", lesson: {js(lesson)},
    hints: [], progress: {{}}, discover: "/kibana/app/discover#/", waf_box: "cr-1-waf", waf_rules: "/etc"}}}};
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
  if (request.route === "/api/sessions/1/scenario/start/") {{
    range.state = {{...range.state, started: true}};
    return {{body: range.state}};
  }}
  if (request.route === "/api/sessions/1/ingest/") return {{body: {{ingested: 0}}}};
  if (request.route === "/api/sessions/1/close/") {{
    range.closed += 1;
    return {{body: {{id: 1}}}};
  }}
  if (request.route.startsWith("/api/sessions/1/lesson/steps/")) {{
    range.steps.push(request.route);
    const checked = request.route.endsWith("/check/");
    if (checked) range.checks.push(request.body);
    const passed = checked && range.passing;
    const id = request.route.split("/")[6];
    return {{body: {{passed, reason: passed ? null : [`scenario.shift.fail.${{id}}`, []],
                    progress: passed ? {{[id]: {{passed: true}}}} : {{}}}}}};
  }}
  return {{status: 404, body: {{detail: "not served"}}}};
}});
"""

SCENARIO_ROUTE = 'if (request.route === "/api/sessions/1/scenario/") return'

def test_a_console_opened_from_the_start_button_names_the_scenario_in_its_breadcrumb_as_the_session_page_does(client):
    catalogue = js([{"id": "board", "name": "Board", "scenarios": [{"id": CARD["id"], "title": CARD["title"]}]}])
    setup = serving(status(started=False)).replace(
        SCENARIO_ROUTE, f'if (request.route === "/api/wargames/") return {{body: {catalogue}}};\n  {SCENARIO_ROUTE}')
    seen = open_page(client, "/blue/1/", setup=setup, scenario="return browser.text('crumbs');")

    assert SCENARIO_ROUTE in serving(status()) and seen["errors"] == []
    assert seen["result"] == " / ".join([
        worded("crumb.home"), f'{worded("wargame.board.name")} · {CARD["id"]} {worded(CARD["title"])}',
        worded("blue.title")]), "the name comes from the API, and no bare kind word follows it"

def test_the_briefing_shows_the_full_length_until_start_and_start_begins_the_clock_once(client):
    waiting = status(started=False, time_left=CARD["minutes"] * 60)
    seen = open_page(client, "/blue/1/", setup=serving(waiting), scenario="""
      const starts = () => browser.requests.filter((r) => r.route.endsWith('/scenario/start/')).length;
      const before = {shown: !browser.element('briefing').classList.contains('hidden'), time: browser.text('briefing-time'), starts: starts()};
      await browser.click('briefing-start');
      await browser.settle();
      await browser.click('scenario-briefing-open');
      await browser.click('briefing-start');
      await browser.settle();
      return {before, starts: starts()};
    """)

    assert seen["errors"] == []
    assert seen["result"]["before"]["shown"] and seen["result"]["before"]["starts"] == 0
    assert f'{CARD["minutes"]}:00' in seen["result"]["before"]["time"], "the clock does not run while the briefing is read"
    assert seen["result"]["starts"] == 1, "reopening the briefing does not start the clock again"

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
        assert label not in result["listed"].lower().replace(worded("triage.attack").lower(), "").replace(
            worded("triage.customer").lower(), "")
    assert result["posted"] == [{"item": "a1", "verdict": "customer"},
                                {"item": "b2", "verdict": "attack", "succeeded": False}]

def test_a_guide_card_shows_once_the_briefing_starts_and_stays_readable_in_the_note_after_it_is_dismissed(client):
    waiting = status(started=False, cards=["blocked"])
    seen = open_page(client, "/blue/1/", setup=serving(waiting), scenario="""
      await browser.click('briefing-start');
      const shown = document.querySelectorAll('#scenario-cards [data-card]').length;
      await browser.click('#scenario-cards [data-card] button');
      await browser.settle();
      const read = document.querySelectorAll('#scenario-cards [data-read]').map((one) => one.textContent);
      return {shown, read, hidden: browser.element('scenario-cards').classList.contains('hidden')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["shown"] == 1, "the card shows on start, not on the next poll"
    assert seen["result"]["hidden"] is False
    assert [worded("scenario.korean.card.blocked.title") in one and worded("scenario.korean.card.blocked.body") in one
            for one in seen["result"]["read"]] == [True]

def test_a_scenario_with_no_guide_card_due_shows_its_goal_in_the_note_instead_of_an_empty_panel(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(cards=[])), scenario="""
      await browser.click('briefing-start');
      const brief = document.querySelector('#scenario-cards [data-brief]');
      return {text: brief.textContent, open: brief.open, hidden: browser.element('scenario-cards').classList.contains('hidden')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["hidden"] is False and seen["result"]["open"] is True
    assert worded(CARD["briefing"]["goal"]) in seen["result"]["text"]

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

def test_scenario_1_1_starts_on_judging_an_alert_and_not_on_opening_the_alert_list_it_opens_with():
    lesson = wargames.lesson("board", lesson_id="1.1")

    assert [step["check"]["kind"] for step in lesson["steps"]][:1] == ["triage"], (
        "a first step telling the learner to open the alert list passed by itself, since the list is open already")

def test_the_count_of_right_judgements_moves_with_the_right_mark_it_counts(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1")), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      const before = browser.text('triage-count');
      await browser.click('[data-item="a1"] [data-judge="customer"]');
      await browser.settle();
      return {before, after: browser.text('triage-count'), said: browser.text('triage-list').includes(STRINGS['triage.said.right'])};
    """)

    assert seen["errors"] == []
    assert seen["result"]["said"] is True
    assert seen["result"]["before"] == worded("triage.count", 0, len(ITEMS))
    assert seen["result"]["after"] == worded("triage.count", 1, len(ITEMS)), (
        "the item said right while the header still counted none right until the next click")

LATE = {**ITEMS[0], "item": "c3", "first": "2026-10-13T06:05:00+00:00", "request": {"method": "GET", "path": "/search/?q=late"}}

def test_an_item_that_arrives_after_the_attack_is_judged_is_listed_without_a_reload(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1")), scenario="""
      await browser.click('briefing-start');
      await browser.click('[data-pane="triage"]');
      await browser.click('[data-item="b2"] [data-judge="attack"]');
      await browser.click('[data-item="b2"] [data-succeeded="false"]');
      await browser.settle();
      range.items = [...range.items, %s];
      await browser.wait(16000);
      await browser.settle();
      return browser.text('triage-list').includes('/search/?q=late');
    """ % js(LATE))

    assert seen["errors"] == []
    assert seen["result"] is True, "the poll stopped once the attack's got-in buttons were shown, so new items waited for a reload"

def test_a_final_check_refused_for_unjudged_items_says_how_many_and_lists_them(client):
    refusing = serving(status(JUDGEMENT, id="1.1")).replace(
        'if (request.route === "/api/sessions/1/scenario/verify-window/") {',
        'if (request.route === "/api/sessions/1/scenario/verify-window/" && range.items.length > 2) {\n'
        '    return {status: 409, body: {detail: "not judged", unjudged: 1}};\n  }\n'
        '  if (request.route === "/api/sessions/1/scenario/verify-window/") {')
    seen = open_page(client, "/blue/1/", setup=refusing, scenario="""
      await browser.click('briefing-start');
      range.items = [...range.items, %s];
      await browser.click('scenario-done');
      await browser.settle();
      return {said: browser.text('scenario-done-said'), listed: browser.text('triage-list').includes('/search/?q=late'),
              windowed: range.windowed, squeezed: browser.element('scenario-strip').contains(browser.element('scenario-done-said'))};
    """ % js(LATE))

    assert seen["errors"] == []
    assert seen["result"] == {"said": worded("scenario.done.unjudged", 1), "listed": True, "windowed": 0, "squeezed": False}, (
        "the refusal sat in the one-line status bar and was cut off")

def test_the_note_at_the_end_of_a_guided_scenario_speaks_of_the_scenario_not_a_lesson(client):
    lesson = {"id": "1.1", "text": "scenario.shift",
              "steps": [{"id": "done", "point": {"panel": "#scenario-done"}, "check": {"kind": "triage", "judged": "verified"}}]}
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1"), lesson=lesson), scenario="""
      await browser.click('briefing-start');
      await browser.click('scenario-done');
      for (let i = 0; i < 4; i += 1) await browser.wait(5000);
      await browser.click('step-next');
      await browser.settle();
      return {task: browser.text('step-task'), said: browser.text('step-status') + browser.text('lesson-body')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["task"] == worded("scenario.note.done")
    assert worded("lesson.done") not in seen["result"]["said"]

TRIAGE_STEPS = [{"id": "attack", "point": {"panel": "#triage-list", "opens": "triage"}, "check": {"kind": "triage", "judged": "attack"}},
                {"id": "all", "point": {"panel": "#triage-list", "opens": "triage"}, "check": {"kind": "triage", "judged": "all"}},
                {"id": "done", "point": {"panel": "#scenario-done"}, "check": {"kind": "triage", "judged": "verified"}}]

def guided(steps=TRIAGE_STEPS):
    return {"id": "1.1", "text": "scenario.shift", "steps": steps}

def test_a_customer_verdict_on_the_attack_step_checks_it_silently_and_shows_no_failure(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1"), lesson=guided()), scenario="""
      range.passing = false;
      await browser.click('[data-pane="triage"]');
      await browser.click('[data-item="a1"] [data-judge="customer"]');
      for (let i = 0; i < 3; i += 1) await browser.settle();
      return {checks: range.checks, said: browser.element('step-said').classList.contains('hidden') ? "" : browser.text('step-said')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["checks"] and all(body == {"poll": True} for body in seen["result"]["checks"]), (
        "a customer verdict ran the attack step's check as the learner's own try")
    assert seen["result"]["said"] == ""

def test_a_passed_triage_step_goes_back_to_unpassed_when_its_next_check_fails(client):
    later = [TRIAGE_STEPS[1], TRIAGE_STEPS[2]]
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1"), lesson=guided(later)), scenario="""
      for (let i = 0; i < 5; i += 1) await browser.wait(1000);
      const passed = {said: browser.text('step-said'), next: browser.text('step-next')};
      range.passing = false;
      for (let i = 0; i < 5; i += 1) await browser.wait(1000);
      return {passed, lapsed: {said: browser.element('step-said').classList.contains('hidden') ? "" : browser.text('step-said'),
                               next: browser.text('step-next')}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["passed"]["next"] == worded("lesson.coach.next")
    assert seen["result"]["lapsed"] == {"said": "", "next": worded("lesson.skip")}, (
        "the note kept saying every item was judged right after a new item came in")

def test_a_scenario_already_started_opens_on_the_console_not_the_briefing(client):
    seen = open_page(client, "/blue/1/", setup=serving(status(JUDGEMENT, id="1.1", started=True)), scenario="""
      return browser.element('briefing').classList.contains('hidden');
    """)

    assert seen["errors"] == []
    assert seen["result"] is True, "a fresh browser showed the briefing's start button for a scenario already running"

def test_a_passed_scenario_offers_no_final_check_or_hint_and_ends_from_the_console(client):
    passed = status(JUDGEMENT, id="1.1", started=True, phase="passed", windows=1,
                    hints={"offer": {"reason": "check", "about": "attack", "at": "x"}, "opened": [], "left": 3},
                    completion={"state": "passed", "reasons": [], "fix": None})
    seen = open_page(client, "/blue/1/", setup=serving(passed), scenario="""
      const hidden = (id) => browser.element(id).classList.contains('hidden');
      const shown = {done: !hidden('scenario-done'), offer: !hidden('scenario-offer'), clock: !hidden('scenario-clock'),
                     end: !hidden('scenario-end'), phase: browser.text('scenario-phase')};
      await browser.click('scenario-end');
      const asked = !hidden('scenario-end-confirm') && range.closed === 0;
      await browser.click('scenario-end-yes');
      for (let i = 0; i < 3; i += 1) await browser.settle();
      return {shown, asked, closed: range.closed, at: location.href};
    """)

    assert seen["errors"] == []
    assert seen["result"]["shown"] == {"done": False, "offer": False, "clock": False, "end": True,
                                       "phase": worded("scenario.phase.passed")}
    assert seen["result"]["asked"] is True and seen["result"]["closed"] == 1
    assert seen["result"]["at"].endswith("/session/1/")

DEBRIEF = """const DEBRIEF = {overview: {verified: 1, steps: {passed: 0, total: 0}, help: {hints: 0}, fix: null},
  customers: {sent: 10, served: 9, blocked: 0, unanswered: 1, other: 0, in_window: [0], blocked_actions: {}},
  timeline: [], task_class: "detection", triage: {right: 0, items: 0, first_try: 0}, evidence: [],
  change: {before: {paranoia: 1}, after: {paranoia: 1}, diff: [], ids: ["+alert http any any -> any any (sid:9000200;)"]},
  cases: [], risk: [], at: {opened: "2026-10-18T09:00:00Z", verified: null}};
"""

def test_the_result_report_keeps_ending_the_session_one_click_away_and_says_what_changed_on_the_ids(client):
    passed = status(JUDGEMENT, id="1.1", started=True, phase="passed", windows=1,
                    completion={"state": "passed", "reasons": [], "fix": None})
    served = DEBRIEF + serving(passed).replace(
        'if (request.route === "/api/sessions/1/ingest/")',
        'if (request.route === "/api/sessions/1/scenario/debrief/") return {body: DEBRIEF};\n  '
        'if (request.route === "/api/sessions/1/ingest/")')
    seen = open_page(client, "/blue/1/", setup=served, scenario="""
      const hidden = (id) => browser.element(id).classList.contains('hidden');
      await browser.click('scenario-phase');
      for (let i = 0; i < 3; i += 1) await browser.settle();
      const report = {open: !hidden('scenario-debrief'), end: !hidden('scenario-debrief-end'),
                      text: browser.text('scenario-debrief-body')};
      await browser.click('scenario-debrief-end');
      return {report, asked: !hidden('scenario-end-confirm'), covered: !hidden('scenario-debrief')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["report"]["open"] is True and seen["result"]["report"]["end"] is True
    assert worded("lesson.debrief.change.ids") in seen["result"]["report"]["text"]
    assert worded("lesson.debrief.change.none") not in seen["result"]["report"]["text"]
    assert worded("scenario.debrief.customers.rest", 1, 0) in seen["result"]["report"]["text"]
    assert (seen["result"]["asked"], seen["result"]["covered"]) == (True, False), (
        "the report covered the strip, and with it the button that ends the session")

