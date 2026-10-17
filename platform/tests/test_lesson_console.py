import json

import pytest

import wargames
from api import views
from console import strings
from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

UNIT = "f4"
RIGHT = {
    "engine": "suricata", "verdict": "403", "address": "172.30.0.1", "meaning": "2xx",
    "stopped": "waf", "rule": "942100", "requests": "2065", "excluded": "942100", "leaked": "admin", "lost": "1",
}

def taught(unit=UNIT):
    return wargames.lesson("board", lesson_id=unit)

def steps_of(unit=UNIT):
    return taught(unit)["steps"]

def ids(unit=UNIT):
    return [step["id"] for step in steps_of(unit)]

def commands(unit=UNIT):
    return {step["id"]: step["command"] for step in steps_of(unit) if step.get("command")}

def shown(unit):
    return [
        {key: value for key, value in views._shown_step(None, dict(step, query=None)).items() if key != "command"}
        | ({"query": step["query"], "discover": f"/kibana/app/discover#/?narrowed={step['id']}"} if step.get("query") else {})
        for step in steps_of(unit)
    ]

GUIDED = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
const range = {sent: [], passed: false, used: [], ended_at: null, progress: {}, checked: [], states: []};
const TEXT = TEXT_JSON;
const FULL = FULL_JSON;
const RIGHT = RIGHT_JSON;
const WITHHELD = WITHHELD_JSON;
const COMMANDS = COMMANDS_JSON;
const revealed = () => Object.fromEntries(Object.entries(range.progress).map(([id, kept]) => [id, {...kept,
  ...(kept.hint >= 3 ? {answer: WITHHELD[id].answer} : {}), ...(kept.passed ? {line: WITHHELD[id].line} : {}),
  ...(kept.reached && COMMANDS[id] ? {command: COMMANDS[id]} : {})}]));
const own = (id) => (range.progress[id] = range.progress[id] || {hint: 0, wrong: 0, passed: null, skipped: null});
const used = (entry) => { if (!range.used.some((one) => one.step === entry.step && one.level === entry.level)) range.used.push(entry); };
const stepState = (id, extra) => ({...extra, hint: own(id).hint, hints: range.used, progress: revealed()});
const passing = (id) => { own(id).passed = own(id).passed || "now"; return stepState(id, {passed: true, reason: null}); };
const failing = (id, poll, key, values) => {
  const kept = own(id);
  if (!poll && (kept.wrong += 1) >= 2) {
    kept.wrong = 0;
    kept.hint = Math.min(4, kept.hint + 1);
    used({step: id, level: "hint"});
  }
  return stepState(id, {passed: false, reason: [key, values || []]});
};
const judge = (id, body) => {
  const check = FULL[id];
  const fail = `${TEXT}.fail.${id}`;
  if (check.kind === "click") return passing(id);
  if (check.kind === "answer" || check.kind === "choice") {
    const given = String(body.answer || "").trim();
    if (given === RIGHT[id]) return passing(id);
    return failing(id, false, (check.known || []).includes(given) ? `${TEXT}.wrong.${id}.${given}` : "lesson.check.wrong");
  }
  if (check.kind === "sent") {
    range.checked.push(body);
    return range.sent.some((path) => new RegExp(check.match).test(path)) ? passing(id) : failing(id, body.poll, fail);
  }
  return range.passed ? passing(id) : failing(id, body.poll, fail);
};
browser.serve((request) => {
  const parts = request.route.split("/");
  const stepped = parts[4] === "lesson" && parts[5] === "steps" ? [request.route, parts[6], parts[7] ? `${parts[7]}/` : ""] : null;
  if (stepped && !stepped[2]) {
    const id = stepped[1];
    range.states.push([id, request.body.state]);
    if (request.body.state === "reached") own(id).reached = own(id).reached || "now";
    else if (!own(id).passed) own(id).skipped = "now";
    return {body: stepState(id, {})};
  }
  if (stepped && stepped[2] === "check/") return {body: judge(stepped[1], request.body)};
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: GUIDANCE, hints: range.used, progress: revealed(), ended_at: range.ended_at, waf_box: "fsl-1-waf", discover: "/kibana/app/discover#/",
                   site: {port: 8002, path: "/site/1/board.com/"},
                   waf_rules: "/etc/modsecurity.d/owasp-crs/rules", lesson: GUIDANCE ? {
      text: TEXT, group: "foundations", cases: CASES_JSON,
      steps: STEPS_JSON, theory: THEORY_JSON, hints: HINTS_JSON,
    } : null}};
  }
  if (request.route === "/api/sessions/1/ingest/") return {body: {ingested: 0}};
  if (request.route === "/api/sessions/1/lesson/hints/") {
    used(request.body);
    own(request.body.step).hint = Math.min(4, own(request.body.step).hint + 1);
    return {body: stepState(request.body.step, {})};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def guided(guidance=True, unit=UNIT):
    lesson = taught(unit)
    return GUIDED.replace("GUIDANCE", "true" if guidance else "false").replace(
        "TEXT_JSON", json.dumps(lesson["text"])).replace(
        "CASES_JSON", json.dumps(lesson["cases"])).replace(
        "THEORY_JSON", json.dumps(lesson["theory"])).replace(
        "HINTS_JSON", json.dumps(lesson["hints"])).replace(
        "STEPS_JSON", json.dumps(shown(unit))).replace(
        "FULL_JSON", json.dumps({step["id"]: step["check"] for step in lesson["steps"]})).replace(
        "RIGHT_JSON", json.dumps(RIGHT)).replace(
        "WITHHELD_JSON", json.dumps({step_id: {part: strings.both(f"{lesson['text']}.{part}.{step_id}")
                                               for part in ("answer", "line")} for step_id in ids(unit)})).replace(
        "COMMANDS_JSON", json.dumps(commands(unit)))

CATALOGUE = """
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [
      {id: "board", name: "Board", description: "", cases: 1,
       foundations: [{id: "f1", order: 1, title: "lesson.range.title", goal: "lesson.range.summary",
                      learns: "lesson.range.learns", minutes: 10, level: "easy", defense: DECLARED,
                      prerequisites: [], steps: 4}]},
      {id: "corp", name: "Corp", description: "", cases: 1, foundations: []},
    ]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 9}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_foundation_starts_guided_on_the_defense_it_declares_and_the_wargame_starts_unguided(client):
    def started(declared, button):
        seen = open_page(client, "/", setup=CATALOGUE.replace("DECLARED", f'"{declared}"'), scenario=f"""
          await browser.click('{button}');
          return browser.requests.filter((r) => r.method === 'POST').map((r) => r.body);
        """)
        assert seen["errors"] == []
        return seen["result"]

    for declared in ("minimal", "full"):
        assert started(declared, '[data-lesson-id="f1"]') == [
            {"scenario": "board", "guidance": True, "lesson": "f1", "defense": declared}]
    assert started("minimal", '[data-wargame-start="board"] button') == [{"scenario": "board"}]

COACHED = """
Object.getPrototypeOf(document.body).getBoundingClientRect =
  () => ({left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0});
const pane = browser.element('pane-frame');
pane.getBoundingClientRect = () => ({left: 200, top: 50, right: 1000, bottom: 650, width: 800, height: 600});
browser.element('pane-body').getBoundingClientRect = pane.getBoundingClientRect;
const present = new Set();
const table = {getBoundingClientRect: () => ({left: 10, top: 20, right: 110, bottom: 60, width: 100, height: 40})};
pane.contentDocument = {
  querySelector: (selector) => (present.has(selector) ? table : null),
  addEventListener() {},
};
"""

def coached(guidance=True, unit=UNIT):
    return guided(guidance, unit) + COACHED

def at(step, unit=UNIT):
    return ids(unit).index(step)

def to(step, unit=UNIT):
    return f"await browser.click('[data-step=\"{at(step, unit)}\"]');"

def hints(times):
    return "for (let i = 0; i < %d; i += 1) await browser.click('coach-pop-hint');" % times

def test_the_sent_check_asks_the_platform_and_never_reads_the_records_itself(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      const poll = async () => { for (let i = 0; i < 5; i += 1) await browser.wait(1000); };
      await poll();
      const nothing = browser.text('coach-pop-title');
      range.sent.push("/search/?q=서울 맛집");
      await poll();
      await browser.wait(1500);
      return {nothing, after: browser.text('coach-pop-title'),
              polls: range.checked.length > 0 && range.checked.every((body) => body.poll === true),
              wrong: range.used.length,
              read: browser.requests.filter((r) => r.route.includes('/detections/') || r.route.includes('/site/requests/')).length};
    """)
    result = seen["result"]

    assert result["nothing"] == english("lesson.logs.label.search")
    assert result["after"] == english("lesson.logs.label.engine")
    assert result["polls"] is True and result["wrong"] == 0, "a poll that finds nothing is not a wrong answer"
    assert result["read"] == 0, "the platform reads the records and judges; the page only asks"

def test_next_and_a_jump_in_the_list_record_a_step_left_unpassed_as_skipped_and_back_does_not(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      {to("stopped", "f5")}
      document.querySelector('#coach-pop-act [data-act="value"]').value = 'waf';
      document.querySelector('#coach-pop-act [data-act="answer"]').dispatchEvent({{type: 'submit', preventDefault() {{}}}});
      await browser.settle();
      await browser.wait(1500);
      await browser.click('coach-pop-next');
      await browser.click('coach-pop-back');
      await browser.settle();
      return range.states;
    """)

    assert seen["result"] == [
        ["attack", "reached"], ["attack", "skipped"], ["stopped", "reached"], ["rule", "reached"], ["rule", "skipped"],
        ["sqlmap", "reached"], ["rule", "reached"],
    ], "a passed step moves on without a skip; Back is not a skip"

def test_help_is_recorded_on_the_session_only_when_the_learner_asks_for_it(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      {to("rule", "f5")}
      for (let i = 0; i < 60; i += 1) await browser.wait(1000);
      const offered = range.used.length;
      {hints(4)}
      return {{offered, recorded: range.used}};
    """)

    assert seen["result"]["offered"] == 0, "the timer only offers a hint; the learner has not asked for one"
    assert seen["result"]["recorded"] == [{"step": "rule", "level": "hint"}], (
        "help is recorded on the session through the API, once per step"
    )

WAF_TERMINAL = """
const pasted = [];
const entered = [];
pane.contentWindow = {term: {paste: (text) => pasted.push(text), input: (text) => entered.push(text), focus() {}}};
"""

@pytest.mark.parametrize("unit, step_id", [
    ("f4", "search"), ("f4", "engine"), ("f4", "find"), ("f5", "sqlmap"), ("f6", "excluded"),
])
def test_skip_after_the_last_hint_records_the_step_skipped_moves_on_and_performs_nothing(client, unit, step_id):
    seen = open_page(client, "/blue/1/", setup=coached(unit=unit) + WAF_TERMINAL, scenario=f"""
      {to(step_id, unit)}
      const shownBefore = !browser.element('coach-pop-skip').classList.contains('hidden');
      {hints(4)}
      const shownAfter = !browser.element('coach-pop-skip').classList.contains('hidden');
      const before = browser.requests.length;
      await browser.click('coach-pop-skip');
      await browser.settle();
      const asked = browser.requests.slice(before).map((r) => [r.route, r.body && r.body.state]);
      return {{shownBefore, shownAfter, asked, pasted, entered, title: browser.text('coach-pop-title')}};
    """)
    following = ids(unit)[at(step_id, unit) + 1]
    result = seen["result"]

    assert seen["errors"] == []
    assert (result["shownBefore"], result["shownAfter"]) == (False, True)
    assert result["asked"] == [[f"/api/sessions/1/lesson/steps/{step_id}/", "skipped"],
                               [f"/api/sessions/1/lesson/steps/{following}/", "reached"]], (
        "skip only records the skip and the next step reached; nothing is checked or done for the learner")
    assert (result["pasted"], result["entered"]) == ([], [])
    assert result["title"] == english(f"{taught(unit)['text']}.label.{following}")

HIDDEN_WHEN_CLOSED = """
const shown = pane.getBoundingClientRect;
const none = () => ({left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0});
pane.getBoundingClientRect = () => (pane.style.display === "none" ? none() : shown());
"""

@pytest.mark.parametrize("unit, step_id, opens", [("f1", "entry", "topology"), ("f4", "engine", "elk"),
                                                 ("f6", "excluded", "waf"), ("f5", "sqlmap", "site")])
def test_a_step_that_points_at_the_pane_is_highlighted_whichever_pane_is_open(client, unit, step_id, opens):
    seen = open_page(client, "/blue/1/", setup=coached(unit=unit) + HIDDEN_WHEN_CLOSED, scenario=f"""
      {to(step_id, unit)}
      await browser.click('[data-pane="{opens}"]');
      await browser.wait(500);
      const box = browser.element('coach-box');
      return {{shown: !box.classList.contains('hidden'), target: box.dataset.target,
               missing: !browser.element('coach-pop-missing').classList.contains('hidden')}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"shown": True, "target": "pane", "missing": False}

POLLED = ("/ingest/", "/detections/", "/waf/", "/check/", "/site/requests/")

def test_only_an_open_session_s_lesson_and_network_panel_keep_polling(client):
    def polled(setup):
        seen = open_page(client, "/blue/1/", setup=coached() + setup, scenario=f"""
          {to("search")}
          await browser.click('[data-pane="site"]');
          await browser.click('site-dev-toggle');
          const before = browser.requests.length;
          for (let second = 0; second < 12; second += 1) await browser.wait(1000);
          return browser.requests.slice(before).map((r) => r.route);
        """)
        return [route for route in seen["result"] if route.endswith(POLLED)]

    assert polled("range.ended_at = '2026-10-11T00:00:00Z';") == [], (
        "nothing keeps asking the platform about a session that has closed"
    )
    assert {"/api/sessions/1/lesson/steps/search/check/", "/api/sessions/1/site/requests/"} <= set(polled(""))
