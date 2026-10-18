import json
import re

import pytest

import wargames
from tests.browser import english, open_page
from tests.test_strings import tables

pytestmark = pytest.mark.django_db

TEXT = "lesson.demo"
SEARCH = r"^/search/\?(.*&)?q=."
STEPS = [
    {"id": "board_ip", "point": {"opens": "topology", "map": {"label": ["board.com", "sw1"]}},
     "check": {"kind": "answer"}},
    {"id": "path", "point": {"opens": "topology", "map": {"zone": "internet"}},
     "check": {"kind": "answer", "form": "order", "options": ["board.com", "customers", "firewall", "waf"]}},
    {"id": "search", "point": {"opens": "site", "site": "input[name=q]"}, "check": {"kind": "sent", "match": SEARCH}},
    {"id": "method", "point": {"opens": "site", "dev": "general.method"}, "check": {"kind": "answer", "match": SEARCH}},
    {"id": "sort", "point": {"opens": "site", "site": "select[name=sort]", "until": "sent",
                             "then": {"dev": "payload.query"}}, "check": {"kind": "answer", "match": "[?&]sort="}},
    {"id": "source", "point": {"opens": "elk", "kibana": {"doc": "source_ip"}}, "check": {"kind": "answer", "leg": "upstream"}},
    {"id": "rule", "point": {"opens": "elk", "kibana": {"doc": "rule_id"}}, "check": {"kind": "answer"}},
    {"id": "kept", "point": {"opens": "elk", "kibana": {"doc": "rule"}, "keep": True}, "check": {"kind": "answer"}},
    {"id": "logged", "point": {"opens": "elk", "kibana": {"hits": True}},
     "check": {"kind": "choice", "options": ["present", "absent"]}},
    {"id": "sqlmap", "point": {"opens": "kali", "term": {"pane": "kali", "match": r"\$ $", "done": r"\[\*\] ending @"}},
     "command": "sqlmap -u \"http://board.com/?sort=posts_post.id*\" --batch", "check": {"kind": "kali"}},
    {"id": "verdict", "point": {"opens": "kali", "term": {"pane": "kali", "match": "injectable", "idle": r"\$ "}},
     "check": {"kind": "choice", "options": ["yes", "no"]}},
    {"id": "run_source", "point": {"opens": "elk", "kibana": {"sidebar": "source_ip"}}, "check": {"kind": "answer"}},
    {"id": "loot", "point": {"opens": "kali", "term": {"pane": "kali", "match": r"^\|"}}, "check": {"kind": "loot"}},
    {"id": "address", "point": {"opens": "site", "panel": "#site-address"}, "check": {"kind": "answer"}},
    {"id": "write", "point": {"opens": "rules", "panel": "#lesson-rules"}, "check": {"kind": "rules"}},
    {"id": "replay", "point": {"opens": "site"}, "check": {"kind": "replay"}},
    {"id": "cost", "point": {"panel": "#lesson-objectives .total"}, "check": {"kind": "answer"}},
    {"id": "db_ip", "solo": True, "point": {"opens": "topology"}, "check": {"kind": "answer"}},
]
RIGHT = {"board_ip": "10.30.0.63", "path": "customers > firewall > waf > board.com", "method": "GET",
         "sort": "sort", "source": "5.188.10.10", "logged": "absent", "verdict": "no", "cost": "22",
         "db_ip": "172.18.0.2"}
OBJECTIVES = {"rows": [{"id": "board-auth-user-partial", "difficulty": 2, "lost": True, "detected": False, "points": 4},
                       {"id": "board-auth-user-admin", "difficulty": 4, "lost": False, "detected": False, "points": 0}],
              "total": 4}
ids = [step["id"] for step in STEPS]

SERVED = """
const range = {sent: [], passed: false, used: [], ended_at: null, progress: {}, checked: [], states: [], moved: [],
               reloaded: 0, answers: []};
location.reload = () => { range.reloaded += 1; };
const STEPS = STEPS_JSON;
const RIGHT = RIGHT_JSON;
const FULL = Object.fromEntries(STEPS.map((step) => [step.id, step.check]));
const own = (id) => (range.progress[id] = range.progress[id] || {hint: 0, wrong: 0, passed: null, skipped: null});
const used = (entry) => { if (!range.used.some((one) => one.step === entry.step)) range.used.push(entry); };
const stepState = (id, extra) => ({...extra, hint: own(id).hint, hints: range.used, progress: range.progress});
const passing = (id, extra) => {
  own(id).passed = own(id).passed || "now";
  own(id).ok = {en: `${id} passed`, ko: `${id} 통과`};
  return stepState(id, {passed: true, reason: null, ...extra});
};
const failing = (id, poll, key) => {
  const kept = own(id);
  if (!poll && (kept.wrong += 1) >= 2) {
    kept.wrong = 0;
    kept.hint = Math.min(3, kept.hint + 1);
    used({step: id, level: "hint"});
  }
  return stepState(id, {passed: false, reason: [key, []]});
};
const judge = (id, body) => {
  const check = FULL[id];
  range.checked.push([id, body]);
  if (check.kind === "answer" || check.kind === "choice") {
    range.answers.push([id, body.answer]);
    return String(body.answer || "").trim() === RIGHT[id] ? passing(id) : failing(id, false, "lesson.check.wrong");
  }
  if (check.kind === "sent") {
    return range.sent.some((path) => new RegExp(check.match).test(path)) ? passing(id) : failing(id, body.poll, "lesson.demo.fail");
  }
  if (check.kind === "kali") {
    return range.passed ? passing(id, {kali: {name: "board-sqli-orderby-sqlmap", requests: 1539, sensors: {firewall: 1539},
                                              discover: "/kibana/app/discover#/?run=sqlmap"}})
      : failing(id, body.poll, "lesson.demo.fail");
  }
  if (check.kind === "replay") {
    return range.passed ? passing(id) : failing(id, body.poll, range.attacked ? "lesson.check.replay_benign" : "lesson.check.replay_attack");
  }
  return range.passed ? passing(id) : failing(id, body.poll, "lesson.demo.fail");
};
browser.serve((request) => {
  const parts = request.route.split("/");
  const stepped = parts[4] === "lesson" && parts[5] === "steps" ? [parts[6], parts[7] ? `${parts[7]}/` : ""] : null;
  if (stepped && !stepped[1]) {
    range.states.push([stepped[0], request.body.state]);
    if (request.body.state === "reached") own(stepped[0]).reached = "now";
    else if (!own(stepped[0]).passed) own(stepped[0]).skipped = "now";
    return {body: stepState(stepped[0], {})};
  }
  if (stepped && stepped[1] === "check/") return {body: judge(stepped[0], request.body)};
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", lesson_id: "f9", next_lesson: NEXT_JSON, guidance: true, hints: range.used,
                   progress: range.progress, ended_at: range.ended_at, waf_box: "waf", discover: "/kibana/app/discover#/",
                   kind: "lesson", kali_terminal: "/vm-terminal/kali/?arg=1", site: {port: 8002, path: "/site/1/board.com/"},
                   waf_rules: "/etc/modsecurity.d/owasp-crs/rules", lessons: [{id: "f1"}, {id: "f9"}],
                   lesson_objectives: OBJECTIVES_JSON,
                   lesson: {text: "lesson.demo", group: "foundations", steps: STEPS, theory: [{id: "one"}], hints: []}}};
  }
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", foundations: [{id: "f1", title: "lesson.map.title"}, {id: "f9", title: "lesson.demo.title"}]}]};
  }
  if (request.route === "/api/sessions/1/score/") {
    return {body: {breaches: [{key: "t-a", detected: false}, {key: "t-b", detected: true}],
                   per_case: [{malicious: true, detected: true}, {malicious: true, detected: false},
                              {malicious: false, detected: false}, {malicious: false, detected: false}, {malicious: false, detected: true}]}};
  }
  if (request.route === "/api/wargames/board/objectives/") {
    return {body: [{key: "t-a", difficulty: 3}, {key: "t-b", difficulty: 4}, {key: "t-c", difficulty: 5}]};
  }
  if (request.route === "/api/topology/") return {body: {source: "gns3", web_ui: {port: 3080, path: "/static/web-ui/fsl-auditor.html?project=p"}}};
  if (request.route === "/api/sessions/1/ingest/") return {body: {ingested: 0}};
  if (request.route === "/api/sessions/1/lesson/") {
    range.moved.push(request.body);
    return {body: {id: 1}};
  }
  if (request.route === "/api/sessions/1/close/") {
    range.ended_at = "now";
    return {body: {id: 1}};
  }
  if (request.route === "/api/sessions/1/lesson/hints/") {
    used(request.body);
    own(request.body.step).hint = Math.min(3, own(request.body.step).hint + 1);
    return {body: stepState(request.body.step, {})};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

LAID_OUT = """
const RECTS = new Map();
const NONE = {left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0};
const box = (left, top, width, height) => ({left, top, width, height, right: left + width, bottom: top + height});
Object.getPrototypeOf(document.body).getBoundingClientRect = function () { return RECTS.get(this) || NONE; };
const placeAt = (reference, rect) => RECTS.set(browser.element(reference), rect);
placeAt('pane', box(60, 56, 980, 744));
placeAt('pane-body', box(60, 96, 980, 704));
placeAt('lesson', box(1040, 56, 400, 744));
['pane-frame', 'site-frame', 'kali-frame', 'topology-frame'].forEach((id) => placeAt(id, box(60, 96, 980, 704)));
placeAt('lesson-objectives-total', box(1380, 300, 40, 20));
placeAt('site-dev-toggle', box(980, 60, 50, 28));
const posted = [];
const asked = (id) => ({postMessage: (data, origin) => posted.push({frame: id, data, origin})});
browser.element('site-frame').contentWindow = asked('site');
browser.element('topology-frame').contentWindow = asked('map');
const answer = (id, rect, text) => {
  const frame = browser.element(id);
  const last = posted.filter((one) => one.frame === (id === 'site-frame' ? 'site' : 'map') && one.data.locate).pop();
  window.dispatchEvent({type: 'message', data: {located: last.data.id, rect, text}, source: frame.contentWindow, origin: last.origin});
};
const kibana = new Map();
browser.element('pane-frame').contentDocument = {
  querySelector: (selector) => (kibana.has(selector) ? {getBoundingClientRect: () => kibana.get(selector)} : null),
};
const kaliLines = ["ubuntu@kali:~$ "];
const screen = {getBoundingClientRect: () => box(0, 0, 960, 480)};
browser.element('kali-frame').contentWindow = {term: {rows: 24, cols: 80, element: {querySelector: () => screen},
  buffer: {active: {get length() { return kaliLines.length; }, viewportY: 0,
                    getLine: (row) => ({isWrapped: typeof kaliLines[row] === 'object',
                                        translateToString: () => kaliLines[row].text ?? kaliLines[row]})}}}};
const shown = (id) => !browser.element(id).classList.contains('hidden');
const styled = (id) => {
  const style = browser.element(id).style;
  return {left: parseFloat(style.left), top: parseFloat(style.top), width: parseFloat(style.width), height: parseFloat(style.height)};
};
const callout = () => (shown('coach-callout') ? {left: parseFloat(browser.element('coach-callout').style.left),
  top: parseFloat(browser.element('coach-callout').style.top), width: 220, height: 28} : null);
const meets = (a, b) => Boolean(a && b) && a.left < b.left + b.width && b.left < a.left + a.width
  && a.top < b.top + b.height && b.top < a.top + a.height;
const frames = async (count = 2) => { for (let i = 0; i < count; i += 1) await browser.wait(0); };
"""

def served(next_lesson="f10", objectives=OBJECTIVES):
    following = json.dumps({"id": next_lesson, "text": "lesson.next"} if next_lesson else None)
    return SERVED.replace("STEPS_JSON", json.dumps(STEPS)).replace("RIGHT_JSON", json.dumps(RIGHT)).replace(
        "NEXT_JSON", following).replace("OBJECTIVES_JSON", json.dumps(objectives)) + LAID_OUT

def to(step):
    return f"await browser.click('[data-step=\"{ids.index(step)}\"]'); await frames();"

def answering(value):
    return f"""
      document.querySelector('#step-act [data-act="value"]').value = {json.dumps(value)};
      document.querySelector('#step-act [data-act="answer"]').dispatchEvent({{type: 'submit', preventDefault() {{}}}});
      await browser.settle();
    """

def hints(times):
    return "for (let i = 0; i < %d; i += 1) await browser.click('step-hint');" % times

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

def test_a_lesson_opens_on_its_first_step_s_pane_and_a_step_on_another_pane_offers_a_button_not_a_detour(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      await frames();
      const first = document.querySelector('.pane-tab[aria-selected="true"]').dataset.pane;
      {to("search")}
      const offered = {{shown: shown('step-open'), pane: browser.element('step-open').dataset.pane,
                        text: browser.text('step-open'), task: browser.text('step-task')}};
      await browser.click('step-open');
      await frames();
      return {{first, offered, opened: document.querySelector('.pane-tab[aria-selected="true"]').dataset.pane,
               after: shown('step-open')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["first"] == "topology"
    assert result["offered"] == {"shown": True, "pane": "site", "text": english("lesson.open.site"),
                                 "task": "lesson.demo.coach.search"}, "the task text is never replaced by a detour"
    assert (result["opened"], result["after"]) == ("site", False)

def test_the_note_is_a_column_beside_the_pane_with_the_step_card_on_top_and_the_theory_open_on_a_lesson_s_first_visit(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario="""
      await frames();
      const body = browser.element('lesson-body').children.map((child) => child.id);
      const work = browser.element('work').children.map((child) => child.id);
      const theoryOpen = browser.element('theory-toggle').getAttribute('aria-expanded');
      await browser.click('lesson-collapse');
      const strip = {folded: browser.element('lesson').classList.contains('folded'), text: browser.text('note-strip-text')};
      return {body, work, theoryOpen, strip};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["work"] == ["pane", "lesson"], "the note shrinks the pane instead of covering it"
    assert result["body"][0] == "step-card"
    assert result["body"].index("step-card") < result["body"].index("theory-card")
    assert result["theoryOpen"] == "true"
    assert result["strip"] == {"folded": True, "text": english("lesson.note.strip", 1, len(STEPS))}

def test_silent_polls_of_a_sent_step_write_nothing_and_the_platform_alone_judges(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("search")}
      for (let i = 0; i < 6; i += 1) await browser.wait(1000);
      const quiet = {{said: shown('step-said'), status: browser.text('step-status')}};
      range.sent.push("/search/?q=hello");
      for (let i = 0; i < 6; i += 1) await browser.wait(1000);
      await browser.wait(1600);
      const passed = {{title: browser.text('step-title'), said: browser.text('step-said'), ring: shown('coach-ring'),
                       next: browser.element('step-next').classList.contains('btn-blue'), status: browser.text('step-status')}};
      await browser.click('step-next');
      return {{quiet, passed, polls: range.checked.filter(([id]) => id === 'search').map(([, body]) => body.poll),
               title: browser.text('step-title'),
               read: browser.requests.filter((r) => r.route.includes('/detections/')).length}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["quiet"] == {"said": False, "status": english("lesson.status.auto")}, (
        "a poll that finds nothing is not a failure the learner should read")
    assert result["polls"] and all(result["polls"])
    assert result["passed"] == {"title": "lesson.demo.label.search", "said": "✓ search passed", "ring": False, "next": True,
                                "status": ""}, "an automatically checked step shows its pass line and waits for Next"
    assert result["title"] == "lesson.demo.label.method"
    assert result["read"] == 0

def test_a_pass_is_said_on_the_passed_step_and_the_next_step_opens_on_a_clean_card(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("board_ip")}
      {answering(RIGHT["board_ip"])}
      const passed = {{title: browser.text('step-title'), said: browser.text('step-said'),
                       ok: browser.element('step-said').classList.contains('text-success')}};
      await browser.wait(1600);
      return {{passed, next: browser.text('step-title'), said: shown('step-said')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["passed"] == {"title": "lesson.demo.label.board_ip", "said": "✓ board_ip passed", "ok": True}
    assert (result["next"], result["said"]) == ("lesson.demo.label.path", False)

def test_the_order_picker_posts_the_hosts_in_the_order_pressed_and_a_second_press_takes_one_out(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("path")}
      const press = async (name) => browser.click(`#step-act [data-act="pick"][data-value="${{name}}"]`);
      for (const name of ["customers", "waf", "firewall"]) await press(name);
      await press("waf");
      for (const name of ["waf", "board.com"]) await press(name);
      const picked = document.querySelector('#step-act [data-act="picked"]').textContent;
      await browser.click('#step-act [data-act="order"]');
      return {{picked, answers: range.answers}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["answers"] == [["path", RIGHT["path"]]]
    assert seen["result"]["picked"] == RIGHT["path"]

def test_a_choice_shows_the_shared_label_of_each_option_and_posts_its_key(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("logged")}
      const labels = document.querySelectorAll('#step-act [data-act="choose"]').map((button) => button.textContent);
      await browser.click('#step-act [data-act="choose"][data-value="absent"]');
      return {{labels, answers: range.answers}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["labels"] == [english("lesson.choice.present"), english("lesson.choice.absent")]
    assert seen["result"]["answers"] == [["logged", "absent"]]

def test_help_climbs_nudge_then_hint_then_skip_is_recorded_only_when_asked_and_never_reveals_an_answer(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("source")}
      for (let i = 0; i < 61; i += 1) await browser.wait(1000);
      const offered = range.used.length;
      const climbed = [];
      for (let i = 0; i < 3; i += 1) {{
        await browser.click('step-hint');
        climbed.push({{help: browser.element('step-help').children.map((line) => line.textContent),
                       hint: shown('step-hint'), skip: shown('step-skip')}});
      }}
      return {{offered, climbed, recorded: range.used}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["offered"] == 0, "the timer only offers a hint; the learner has not asked for one"
    assert result["climbed"] == [
        {"help": ["lesson.demo.nudge.source"], "hint": True, "skip": False},
        {"help": ["lesson.demo.nudge.source", "lesson.demo.hint.source"], "hint": True, "skip": False},
        {"help": ["lesson.demo.nudge.source", "lesson.demo.hint.source"], "hint": False, "skip": True},
    ]
    assert result["recorded"] == [{"step": "source", "level": "hint"}]

@pytest.mark.parametrize("step_id", ["search", "logged", "sqlmap"])
def test_skip_records_the_step_skipped_moves_on_and_performs_nothing(client, step_id):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to(step_id)}
      {hints(3)}
      const before = browser.requests.length;
      await browser.click('step-skip');
      await browser.settle();
      return {{asked: browser.requests.slice(before).map((r) => [r.route, r.body && r.body.state]),
               title: browser.text('step-title')}};
    """)
    following = ids[ids.index(step_id) + 1]

    assert seen["errors"] == []
    assert seen["result"]["asked"] == [[f"/api/sessions/1/lesson/steps/{step_id}/", "skipped"],
                                       [f"/api/sessions/1/lesson/steps/{following}/", "reached"]]
    assert seen["result"]["title"] == f"lesson.demo.label.{following}"

def test_the_last_step_is_solo_without_a_highlight_or_hints_and_offers_skip_from_the_start(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("db_ip")}
      await browser.click('[data-pane="topology"]');
      await frames(3);
      return {{ring: shown('coach-ring'), callout: shown('coach-callout'), hint: shown('step-hint'), skip: shown('step-skip'),
               asked: posted.filter((one) => one.data.locate).length}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"ring": False, "callout": False, "hint": False, "skip": True, "asked": 0}

def test_next_and_a_jump_record_a_step_left_unpassed_as_skipped_and_back_does_not(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("method")}
      {answering(RIGHT["method"])}
      await browser.wait(1600);
      await browser.click('step-next');
      await browser.click('step-back');
      await browser.settle();
      return range.states;
    """)

    assert seen["result"] == [
        ["board_ip", "reached"], ["board_ip", "skipped"], ["method", "reached"], ["sort", "reached"], ["sort", "skipped"],
        ["source", "reached"], ["sort", "reached"],
    ], "a passed step moves on without a skip; Back is not a skip"

def test_a_kali_step_shows_the_command_to_type_with_a_copy_button_and_no_button_runs_it_and_its_row_carries_no_count(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("sqlmap")}
      await browser.click('step-open');
      const card = browser.element('step-card');
      const buttons = card.querySelectorAll('button').filter((button) => !button.classList.contains('hidden') && button.id !== 'step-copy')
        .map((button) => button.textContent);
      const command = {{shown: shown('step-command'), text: browser.text('step-command'), copy: shown('step-copy'),
                       wraps: browser.element('step-command').getAttribute('style').includes('white-space: pre-wrap;')
                                && browser.element('step-command').getAttribute('style').includes('word-break: normal')}};
      range.passed = true;
      await browser.click('#step-act [data-act="kali"]');
      await browser.wait(1600);
      const row = browser.element('step-act').querySelector('[data-kali]');
      const stayed = browser.text('step-title');
      await browser.click('step-next');
      return {{buttons, command, stayed, title: browser.text('step-title'), row: row.textContent.trim().replace(/\\s+/g, ' '),
               window: row.querySelector('[data-discover]').dataset.discover}};
    """)
    result = seen["result"]
    step = STEPS[ids.index("sqlmap")]

    assert seen["errors"] == []
    assert result["command"] == {"shown": True, "text": step["command"], "copy": True, "wraps": True}
    assert result["buttons"] == [english("lesson.kali.check"), english("lesson.hint.more"), english("lesson.coach.back"),
                                 english("lesson.coach.next")], "the learner types every attack"
    assert result["stayed"] == "lesson.demo.label.sqlmap", "the pass line stays until the learner presses Next"
    assert result["title"] == "lesson.demo.label.verdict"
    assert "1539" not in result["row"] and "firewall" not in result["row"]
    assert result["row"].endswith(english("lesson.kali.window"))
    assert result["window"] == "/kibana/app/discover#/?run=sqlmap"

def test_opening_kibana_at_the_run_s_time_again_reloads_it_so_a_record_ingested_since_shows(client):
    seen = open_page(client, "/blue/1/", setup=served() + """
let reloaded = 0;
browser.element('pane-frame').contentWindow = {location: {reload: () => { reloaded += 1; }}};
""", scenario=f"""
      {to("sqlmap")}
      range.passed = true;
      await browser.click('#step-act [data-act="kali"]');
      const link = () => browser.element('step-act').querySelector('[data-discover]');
      link().click();
      const first = {{src: browser.element('pane-frame').getAttribute('src'), reloaded}};
      link().click();
      return {{first, again: reloaded}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["first"] == {"src": "/kibana/app/discover#/?run=sqlmap", "reloaded": 0}
    assert seen["result"]["again"] == 1

def test_the_ring_sits_on_the_target_the_pane_alone_is_dimmed_and_the_callout_never_covers_the_target(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("cost")}
      STRINGS.en['lesson.demo.callout.cost'] = 'The total is here';
      await frames();
      const target = {{left: 1380, top: 300, width: 40, height: 20}};
      return {{ring: styled('coach-ring'), dim: shown('coach-dim'), callout: callout(),
               meets: meets(callout(), target), inNote: callout() && callout().left >= 1040 && callout().left + 220 <= 1440}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["ring"] == {"left": 1374, "top": 294, "width": 52, "height": 32}
    assert result["dim"] is False, "a target outside the pane is ringed without dimming the pane"
    assert result["callout"] is not None and result["meets"] is False and result["inNote"] is True, (
        "a target in the note column keeps its callout in the note column, never over the pane")

def test_the_website_and_the_map_are_asked_where_the_target_is_and_their_answer_is_placed_at_the_frame(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      await frames();
      browser.element('topology-frame').contentWindow = browser.element('topology-frame').contentWindow;
      window.dispatchEvent({{type: 'message', data: {{map: 'drawn'}}, source: browser.element('topology-frame').contentWindow}});
      await frames();
      const mapAsked = posted.filter((one) => one.frame === 'map' && one.data.locate).pop();
      answer('topology-frame', {{x: 400, y: 200, w: 90, h: 16}});
      await frames();
      const onMap = styled('coach-ring');
      {to("search")}
      await browser.click('step-open');
      await frames();
      const siteAsked = posted.filter((one) => one.frame === 'site' && one.data.locate).pop();
      answer('site-frame', {{x: 100, y: 50, w: 300, h: 30}});
      await frames();
      return {{mapAsked: mapAsked.data.locate, mapOrigin: mapAsked.origin, onMap,
               stopped: posted.some((one) => one.frame === 'map' && one.data.locate === null),
               siteAsked: siteAsked.data.locate, siteOrigin: siteAsked.origin, onSite: styled('coach-ring'),
               dim: shown('coach-dim'), meets: meets(callout(), {{left: 160, top: 146, width: 300, height: 30}})}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert (result["mapAsked"], result["mapOrigin"]) == ({"label": ["board.com", "sw1"]}, "http://console.test:3080")
    assert result["onMap"] == {"left": 454, "top": 295, "width": 102, "height": 18}
    assert result["stopped"] is True, "the map stops answering once the step no longer points at it"
    assert (result["siteAsked"], result["siteOrigin"]) == ("input[name=q]", "http://console.test:8002")
    assert result["onSite"] == {"left": 154, "top": 145, "width": 312, "height": 32}
    assert result["dim"] is True and result["meets"] is False

def test_the_callout_on_the_website_keeps_off_the_page_content_the_frame_reports_around_the_target(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("search")}
      STRINGS.en['lesson.demo.callout.search'] = 'Type the word here';
      await browser.click('step-open');
      await frames();
      answer('site-frame', {{x: 100, y: 50, w: 300, h: 30}}, [
        {{x: 100, y: 100, w: 500, h: 40}}, {{x: 100, y: 150, w: 500, h: 40}}, {{x: 100, y: 200, w: 500, h: 40}},
        {{x: 100, y: 20, w: 200, h: 20}}]);
      await frames();
      const content = [[160, 196, 500, 40], [160, 246, 500, 40], [160, 296, 500, 40], [160, 116, 200, 20]];
      return {{callout: callout(), over: content.map(([left, top, width, height]) => meets(callout(), {{left, top, width, height}}))}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["callout"] is not None and result["over"] == [False, False, False, False]

DEV = """
const listRows = (picked) => {
  browser.element('site-dev-rows').innerHTML = [
    '<tr data-coach="row" data-url="/search/?q=old" aria-selected="false"></tr>',
    `<tr data-coach="row" data-url="/search/?q=hello" aria-selected="${picked}"></tr>`,
    '<tr data-coach="row" data-url="/static/app.css" aria-selected="false"></tr>',
  ].join('');
  document.querySelectorAll('[data-coach="row"]').forEach((row, index) => RECTS.set(row, box(60, 600 + 20 * index, 400, 20)));
};
const showTabs = (selected) => {
  browser.element('site-dev-detail').innerHTML = ['tab.headers', 'tab.payload'].map((name) =>
    `<button data-coach="${name}" aria-selected="${String(name === selected)}"></button>`).join('')
    + '<div data-coach="general.method"></div><div data-coach="payload.query"></div>';
  ['tab.headers', 'tab.payload', 'general.method', 'payload.query'].forEach((name, index) =>
    RECTS.set(document.querySelector(`[data-coach="${name}"]`), box(500 + 60 * index, 620, 50, 20)));
};
const ringAt = async () => { await frames(); return shown('coach-ring') ? styled('coach-ring').left : null; };
"""

def test_a_developer_tools_step_points_at_the_toggle_then_the_matching_row_then_the_tab_then_the_line(client):
    seen = open_page(client, "/blue/1/", setup=served() + DEV, scenario=f"""
      {to("method")}
      await browser.click('step-open');
      const closed = await ringAt();
      browser.element('site-dev-toggle').setAttribute('aria-pressed', 'true');
      listRows('false');
      showTabs('tab.payload');
      const noRow = await ringAt();
      const rowTop = styled('coach-ring').top;
      listRows('true');
      const wrongTab = await ringAt();
      showTabs('tab.headers');
      const line = await ringAt();
      return {{closed, noRow, rowTop, wrongTab, line}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"closed": 974, "noRow": 62, "rowTop": 619, "wrongTab": 494, "line": 614}, (
        "closed DevTools: the toggle; no row picked: the last row of the step's request; wrong tab: the tab; then the line")

def test_a_step_held_until_its_request_is_sent_then_points_at_what_follows(client):
    seen = open_page(client, "/blue/1/", setup=served() + DEV, scenario=f"""
      {to("sort")}
      await browser.click('step-open');
      await frames();
      const before = posted.filter((one) => one.frame === 'site' && one.data.locate).pop().data.locate;
      browser.element('site-dev-toggle').setAttribute('aria-pressed', 'true');
      listRows('false');
      browser.element('site-dev-rows').innerHTML += '<tr data-coach="row" data-url="/?sort=title" aria-selected="true"></tr>';
      document.querySelectorAll('[data-coach="row"]').forEach((row, index) => RECTS.set(row, box(60, 600 + 20 * index, 400, 20)));
      showTabs('tab.payload');
      window.dispatchEvent({{type: 'message', data: {{site: '/site/1/board.com/?sort=title'}}, source: browser.element('site-frame').contentWindow,
                             origin: 'http://console.test:8002'}});
      const after = await ringAt();
      return {{before, after}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"before": "select[name=sort]", "after": 674}

def test_kibana_and_terminal_steps_ring_the_flyout_row_the_hit_count_and_the_matching_terminal_line(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("rule")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="docTableExpandToggleColumn"]', box(10, 300, 20, 20));
      const toggle = await frames().then(() => styled('coach-ring'));
      kibana.set('[data-test-subj="docViewerFlyout"]', box(500, 0, 480, 704));
      kibana.set('[data-test-subj="unifiedDocViewerFieldsSearchInput"]', box(520, 80, 300, 24));
      const filter = await frames().then(() => styled('coach-ring'));
      kibana.set('[data-test-subj="tableDocViewRow-rule_id-name"]', box(520, 200, 120, 24));
      kibana.set('[data-test-subj="tableDocViewRow-rule_id-value"]', box(640, 200, 300, 24));
      await frames();
      const row = styled('coach-ring');
      {to("verdict")}
      await browser.click('step-open');
      kaliLines.push("[INFO] all tested parameters do not appear to be injectable", "ubuntu@kali:~$ ");
      await frames();
      const line = styled('coach-ring');
      return {{toggle, filter, row, line}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["toggle"] == {"left": 64, "top": 390, "width": 32, "height": 32}, "no flyout open: the row's expand toggle"
    assert result["filter"] == {"left": 574, "top": 175, "width": 312, "height": 26}, (
        "a flyout open without the field's row: the flyout's field filter, since the table renders only some rows")
    assert result["row"] == {"left": 574, "top": 295, "width": 432, "height": 26}
    assert result["line"] == {"left": 60, "top": 116, "width": 714, "height": 20}, (
        "the ring spans the line's text over whole rows and stays inside the pane")

def test_a_terminal_ring_covers_a_wrapped_line_or_a_printed_table_and_its_callout_avoids_the_text(client):
    wrapped = "[CRITICAL] all tested parameters do not appear to be injectable. Try to increase "
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.verdict'] = 'The verdict';
      STRINGS.en['lesson.demo.callout.loot'] = 'The table';
      {to("verdict")}
      await browser.click('step-open');
      kaliLines.push({json.dumps(wrapped)}, {{text: "values for '--level'/'--risk' options"}}, "ubuntu@kali:~$ ");
      await frames();
      const verdict = {{ring: styled('coach-ring'), callout: callout()}};
      {to("loot")}
      kaliLines.push("+----------+--------+", "| username | password |", "+----------+--------+", "| admin    | pbkdf2 |",
                     "| jiwoo    | pbkdf2 |", "+----------+--------+", "", "ubuntu@kali:~$ ");
      await frames();
      const table = {{ring: styled('coach-ring'), callout: callout()}};
      const text = [...Array(kaliLines.length).keys()].map((row) => {{
        const line = kaliLines[row].text ?? kaliLines[row];
        return {{left: 60, top: 96 + row * 20, width: line.trimEnd().length * 12, height: 20}};
      }}).filter((row) => row.width);
      return {{verdict, table, overText: text.some((row) => meets(table.callout, row) || meets(verdict.callout, row))}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["verdict"]["ring"] == {"left": 60, "top": 116, "width": 966, "height": 40}, (
        "both rows of the wrapped line, whole rows, never into the line above")
    assert result["table"]["ring"] == {"left": 60, "top": 176, "width": 282, "height": 120}, "the table and its borders"
    assert result["verdict"]["callout"] and result["table"]["callout"]
    assert result["overText"] is False

def test_no_missing_line_while_a_terminal_runs_a_command_or_a_pane_still_loads(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("sqlmap")}
      await browser.click('step-open');
      kaliLines.splice(0, kaliLines.length, "ubuntu@kali:~$ sqlmap -u x --batch", "[INFO] testing connection");
      await frames(130);
      const busy = {{missing: shown('step-missing'), ring: shown('coach-ring')}};
      {to("board_ip")}
      await frames(130);
      const drawing = shown('step-missing');
      return {{busy, drawing}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"busy": {"missing": False, "ring": False}, "drawing": False}

def test_a_website_step_whose_element_is_not_on_this_page_points_at_the_link_to_the_post_list(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("sort")}
      await browser.click('step-open');
      await frames();
      answer('site-frame', null);
      await frames();
      const home = posted.filter((one) => one.frame === 'site' && one.data.locate).pop().data.locate;
      answer('site-frame', {{x: 10, y: 10, w: 120, h: 24}});
      await frames();
      return {{home, ring: shown('coach-ring'), callout: browser.text('coach-callout'), missing: shown('step-missing')}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"home": "a.navbar-brand", "ring": True, "callout": english("lesson.site.home"), "missing": False}

def visit_without_the_target(client, path):
    return open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("search")}
      await browser.click('step-open');
      await frames();
      window.dispatchEvent({{type: 'message', data: {{site: '/site/1/board.com{path}'}}, source: browser.element('site-frame').contentWindow,
                             origin: 'http://console.test:8002'}});
      await frames();
      answer('site-frame', null);
      await frames();
      answer('site-frame', null);
      await frames();
      return {{at: site.history.slice(-1)[0], coached: dev.coached && dev.coached.path}};
    """)

def test_the_coach_goes_home_from_a_page_the_learner_wandered_to_but_never_from_the_page_their_request_produced(client):
    wandered = visit_without_the_target(client, "/posts/3/")
    sent = visit_without_the_target(client, "/search/?q=%3Cscript%3Ealert(1)%3C/script%3E")

    assert wandered["errors"] == [] and sent["errors"] == []
    assert wandered["result"] == {"at": "/", "coached": "/"}
    assert sent["result"] == {"at": "/search/?q=%3Cscript%3Ealert(1)%3C/script%3E", "coached": None}, (
        "the block page that the learner's request produced stays on screen while the next step reads it"
    )

def test_a_navigation_the_coach_makes_keeps_the_network_rows_and_one_the_learner_makes_clears_them(client):
    seen = open_page(client, "/blue/1/", setup=served() + """
      const watchers = [];
      globalThis.MutationObserver = class { constructor(callback) { watchers.push(callback); } observe() {} };
    """, scenario="""
      const row = (id, url, category = 'doc', status = 200) => ({id, url, category, status, type: category, size: 100, ms: 10});
      const ids = () => dev.rows.map((one) => one.id);
      const srcChanged = () => watchers.forEach((callback) => callback());

      devTake([row(1, 'http://board.com/search/?q=%3Cscript%3E', 'doc', 403)]);
      siteGo('/', true);
      srcChanged();
      const justAfter = ids();
      devTake([row(2, 'http://board.com/')]);
      devLanded('/');
      devTake([row(3, 'http://board.com/static/app.css', 'stylesheet')]);
      const coached = ids();

      siteGo('/posts/1/');
      srcChanged();
      const learnerNavigating = ids();
      devTake([row(5, 'http://board.com/posts/1/')]);
      devLanded('/posts/1/');
      return {justAfter, coached, learnerNavigating, learnerLanded: ids(), pending: dev.coached};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"justAfter": [1], "coached": [1, 2, 3], "learnerNavigating": [], "learnerLanded": [5], "pending": None}, (
        "the coach's own trip home keeps the rows, as with Preserve log; the learner's navigation clears them as Chrome does"
    )

def test_every_step_that_reads_a_kali_run_carries_the_button_that_opens_kibana_at_its_time(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      {to("sqlmap")}
      range.passed = true;
      await browser.click('#step-act [data-act="kali"]');
      await browser.wait(1600);
      {to("run_source")}
      await browser.settle();
      const button = browser.element('step-open');
      return {{window: button.dataset.discover || null, text: browser.text('step-open'), shown: shown('step-open'),
               links: browser.element('step-act').querySelectorAll('[data-discover]').length}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"window": "/kibana/app/discover#/?run=sqlmap", "text": english("lesson.kali.window"), "shown": True,
                              "links": 0}, "one button: the step's open button itself opens the run's window"

def test_the_objectives_card_lists_each_objective_with_its_penalty_and_the_total(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario="""
      await frames();
      return {shown: shown('lesson-objectives'), total: document.querySelector('#lesson-objectives .total').textContent,
              rows: document.querySelectorAll('#lesson-objectives-rows [data-objective]').map((row) =>
                row.querySelectorAll('td').map((cell) => cell.textContent))};
    """)

    assert seen["errors"] == []
    assert seen["result"]["shown"] is True and seen["result"]["total"] == "4"
    assert seen["result"]["rows"][0][1:] == ["2", english("lesson.objectives.lost"), english("common.no"), "4"]

POLLED = ("/ingest/", "/detections/", "/waf/", "/check/", "/site/requests/")

def test_only_an_open_session_s_lesson_and_network_panel_keep_polling(client):
    def polled(setup):
        seen = open_page(client, "/blue/1/", setup=served() + setup, scenario=f"""
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

@pytest.mark.parametrize("following", ["f10", None])
def test_a_finished_foundation_starts_the_next_lesson_and_the_last_one_ends_on_a_course_summary_before_closing(
        client, following):
    seen = open_page(client, "/blue/1/", setup=served(next_lesson=following), scenario=f"""
      {to("db_ip")}
      {answering(RIGHT["db_ip"])}
      const said = browser.text('step-task');
      const counter = browser.element('step-count').classList.contains('hidden');
      const button = Boolean(document.querySelector('#step-act [data-act="next-lesson"]'));
      const early = range.moved.length + browser.requests.filter((r) => r.route.endsWith('/close/')).length;
      await browser.wait(2500);
      const course = document.querySelectorAll('#step-act [data-course]').map((line) => line.dataset.course);
      const waited = browser.requests.filter((r) => r.route.endsWith('/close/')).length;
      const close = document.querySelector('#step-act [data-act="close"]');
      if (close) {{ close.click(); await browser.settle(); }}
      return {{said, counter, button, early, course, waited, moved: range.moved, reloaded: range.reloaded, href: location.href,
               closed: browser.requests.filter((r) => r.route.endsWith('/close/')).length}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["counter"] is True, "no step counter on the finished card"
    assert result["early"] == 0, "the learner reads the line before the next lesson starts"
    if following:
        assert result["said"] == english("lesson.next.ready", "lesson.next.title")
        assert result["button"] is True
        assert (result["moved"], result["reloaded"], result["closed"]) == ([{"lesson": following}], 1, 0)
    else:
        assert result["course"] == ["f1", "f9"]
        assert result["said"] == english("lesson.course.done"), "the last task line is never left empty"
        assert result["waited"] == 0, "the summary stays until the learner closes the session"
        assert (result["moved"], result["closed"]) == ([], 1)
        assert result["href"].endswith("/session/1/")

LOCATORS = {"panel", "map", "site", "dev", "kibana", "term"}
POINT_KEYS = LOCATORS | {"opens", "until", "then", "keep"}
LOCATOR_PANES = {"map": "topology", "site": "site", "dev": "site", "kibana": "elk"}
DEV_NAMES = {"toggle", "row", "tab.headers", "tab.payload", "tab.preview", "tab.response", "general.url",
             "general.method", "general.status", "general.remote", "payload.query"}
SELECTOR_PARTS = re.compile(r'#([\w-]+)|\.([\w-]+)|\[([\w-]+)="([^"]*)"\]')

def stepped():
    return [*wargames.foundations("board"),
            *[wargames.lesson("board", lesson_id=one["id"]) for one in wargames.stepped_scenarios("board")]]

def panel_unresolved(page, selector):
    absent = [
        part for named, cls, attribute, value in SELECTOR_PARTS.findall(selector)
        for part, present in ((f"#{named}", f'id="{named}"' in page),
                              (f".{cls}", bool(re.search(rf'class="[^"]*\b{re.escape(cls)}\b', page))),
                              (f"[{attribute}]", f'{attribute}="{value}"' in page))
        if part not in ("#", ".", "[]") and not present
    ]
    return [f"panel {selector}: {absent}"] if absent else []

def shaped(kind, spec):
    single = next(iter(spec), None) if isinstance(spec, dict) and len(spec) == 1 else None
    return {
        "panel": lambda: isinstance(spec, str) and bool(spec),
        "site": lambda: isinstance(spec, str) and bool(spec),
        "dev": lambda: spec in DEV_NAMES,
        "map": lambda: (single in ("node", "zone") and isinstance(spec[single], str)) or (
            single in ("link", "label") and isinstance(spec[single], list) and len(spec[single]) == 2),
        "kibana": lambda: (single in ("doc", "sidebar") and isinstance(spec[single], str)) or (
            single in ("hits", "query") and spec[single] is True),
        "term": lambda: isinstance(spec, dict) and spec.get("pane") in ("kali", "waf") and isinstance(spec.get("match"), str),
    }[kind]()

def pane_of(kind, spec):
    return spec.get("pane") if kind == "term" and isinstance(spec, dict) else LOCATOR_PANES.get(kind)

def locator_unresolved(page, locator):
    kinds = sorted(set(locator) & LOCATORS)
    if len(kinds) != 1:
        return [f"one locator, not {kinds}"]
    kind, spec = kinds[0], locator[kinds[0]]
    if not shaped(kind, spec):
        return [f"{kind} {spec}"]
    pane = pane_of(kind, spec)
    return [*(panel_unresolved(page, spec) if kind == "panel" else []),
            *([f"pane {pane}"] if pane and f'data-pane="{pane}"' not in page else [])]

def unresolved(page, point, solo):
    located = set(point) & LOCATORS
    first = locator_unresolved(page, point) if located else []
    kind = next(iter(located), None)
    needs = pane_of(kind, point[kind]) if kind and not first else None
    then = point.get("then") or {}
    return [
        *sorted(set(point) - POINT_KEYS),
        *([f"opens {point['opens']}"] if "opens" in point and f'data-pane="{point["opens"]}"' not in page else []),
        *(["a solo step with a locator"] if solo and (located or then) else []),
        *first,
        *([f"{kind} needs {needs}, opens {point['opens']}"] if needs and point.get("opens", needs) != needs else []),
        *(["until is sent, with then"] if "until" in point and (point["until"] != "sent" or not then) else []),
        *(["then without until"] if then and "until" not in point else []),
        *(["then holds only a locator"] if set(then) - LOCATORS else []),
        *([f"then {missing}" for missing in locator_unresolved(page, then)] if then else []),
    ]

def test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console(client):
    page = client.get("/blue/1/").content.decode()
    taught = stepped()
    foundations = {one["id"] for one in wargames.foundations("board")}
    points = [(unit["id"], step["id"], step.get("point") or {}, unit["id"] in foundations and step is unit["steps"][-1])
              for unit in taught for step in unit["steps"]]

    assert len({unit for unit, _, _, _ in points}) == len(taught) > 6
    assert [(unit, step, missing) for unit, step, point, solo in points if (missing := unresolved(page, point, solo))] == []

def test_every_pane_a_step_opens_or_points_into_has_an_open_button_label_in_both_languages():
    table = tables()
    panes = set()
    for unit in stepped():
        for step in unit["steps"]:
            point = step.get("point") or {}
            panes |= {point["opens"]} if "opens" in point else set()
            for locator in (point, point.get("then") or {}):
                kind = next(iter(set(locator) & LOCATORS), None)
                panes |= {pane_of(kind, locator[kind])} - {None} if kind else set()

    assert panes
    assert [(language, f"lesson.open.{pane}") for pane in sorted(panes) for language in ("en", "ko")
            if f"lesson.open.{pane}" not in table[language]] == [], "the step card's open button would show a raw key"

GRID = """
const doc = browser.element('pane-frame').contentDocument;
const plain = doc.querySelector;
const arrows = new Map();
let pageAt = null;
const hop = (row, from, to) => ({row, from, to});
let hops = [];
const cellOf = (row, text, column) => ({
  textContent: `${text}- ${column}, column 5, row ${row + 1}`,
  querySelector: (inner) => (inner === '[data-datagrid-cellcontent]' ? {textContent: text} : null),
  closest: () => ({getAttribute: () => String(row)}),
});
const toggleOf = (row) => ({closest: () => ({getAttribute: () => String(row)}), getBoundingClientRect: () => box(10, 300 + 40 * row, 20, 20)});
doc.querySelectorAll = (selector) => {
  if (selector.includes('"source_ip"')) return hops.map((one) => cellOf(one.row, one.from, 'source_ip'));
  if (selector.includes('"destination"')) return hops.map((one) => cellOf(one.row, one.to, 'destination'));
  if (selector.includes('docTableExpandToggleColumn')) return hops.map((one) => toggleOf(one.row));
  return [];
};
doc.querySelector = (selector) => (selector.includes('NavigationPage')
  ? (pageAt === null ? null : {getAttribute: () => `dscDocNavigationPage-${pageAt}`, getBoundingClientRect: () => box(700, 20, 200, 30),
                              querySelector: (inner) => (arrows.has(inner) ? {getBoundingClientRect: () => arrows.get(inner)} : null)})
  : plain(selector));
"""

def test_a_leg_step_rings_the_expand_toggle_of_the_row_on_that_leg_then_the_arrow_off_a_wrong_document_then_the_value(client):
    seen = open_page(client, "/blue/1/", setup=served() + GRID, scenario=f"""
      STRINGS.en['lesson.kibana.expand.upstream'] = 'Expand the row for the board';
      STRINGS.en['lesson.kibana.other'] = 'Another event';
      {to("source")}
      await browser.click('step-open');
      hops = [hop(0, '175.192.0.10', '10.30.0.102'), hop(1, '10.30.0.102', '10.30.0.63')];
      await frames();
      const expand = {{ring: styled('coach-ring'), text: browser.text('coach-callout')}};
      kibana.set('[data-test-subj="docViewerFlyout"]', box(500, 0, 480, 704));
      pageAt = 0;
      arrows.set('button[data-test-subj="pagination-button-next"]', box(760, 24, 24, 24));
      await frames();
      const other = {{ring: styled('coach-ring'), text: browser.text('coach-callout')}};
      pageAt = 1;
      kibana.set('[data-test-subj="tableDocViewRow-source_ip-value"]', box(640, 200, 300, 24));
      await frames();
      const value = styled('coach-ring');
      return {{expand, other, value}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["expand"] == {"ring": {"left": 64, "top": 430, "width": 32, "height": 32},
                                "text": "Expand the row for the board"}, "the second row: its source is the first row's destination"
    assert result["other"] == {"ring": {"left": 814, "top": 114, "width": 36, "height": 36}, "text": "Another event"}
    assert result["value"] == {"left": 694, "top": 295, "width": 312, "height": 26}, "the right document: the value itself"

def test_a_leg_step_whose_row_cannot_be_found_asks_for_the_destination_and_never_rings_a_flyout_value(client):
    seen = open_page(client, "/blue/1/", setup=served() + GRID, scenario=f"""
      STRINGS.en['lesson.kibana.verify.upstream'] = 'Read the destination first.';
      {to("source")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="docViewerFlyout"]', box(500, 0, 480, 704));
      kibana.set('[data-test-subj="unifiedDocViewerFieldsSearchInput"]', box(520, 80, 300, 24));
      kibana.set('[data-test-subj="tableDocViewRow-source_ip-value"]', box(640, 200, 300, 24));
      await frames();
      const unknown = {{ring: styled('coach-ring'), text: browser.text('coach-callout')}};
      hops = [hop(0, '175.192.0.10', '10.30.0.102'), hop(1, '10.30.0.102', '10.30.0.63')];
      await frames();
      const noPager = {{ring: styled('coach-ring'), text: browser.text('coach-callout')}};
      return {{unknown, noPager}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    filter_ring = {"left": 574, "top": 175, "width": 312, "height": 26}
    assert result["unknown"] == {"ring": filter_ring, "text": "Read the destination first."}
    assert result["noPager"] == result["unknown"], "a document whose position is unknown is never taken for the right one"

def test_a_finished_run_moves_the_ring_from_the_prompt_to_the_check_button(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.kali.press'] = 'The run has finished. Press Check.';
      {to("sqlmap")}
      await browser.click('step-open');
      RECTS.set(document.querySelector('[data-act="kali"]'), box(1060, 400, 130, 28));
      await frames();
      const idle = {{shown: shown('coach-ring'), top: styled('coach-ring').top}};
      kaliLines.splice(0, kaliLines.length, "ubuntu@kali:~$ sqlmap -u x --batch", "[INFO] testing", "ubuntu@kali:~$ ");
      await frames();
      kaliLines.splice(0, kaliLines.length, "ubuntu@kali:~$ sqlmap -u x --batch", "[*] ending @ 10:00:00 /2026-10-19/", "", "ubuntu@kali:~$ ");
      await frames();
      const press = document.querySelector('[data-act="kali"]');
      const line = browser.element('step-coach');
      const done = {{text: browser.text('step-coach'), shown: shown('step-coach'), floating: shown('coach-callout'),
                    below: line.parentNode.children[line.parentNode.children.indexOf(press) + 1] === line,
                    ring: styled('coach-ring'), dim: shown('coach-dim')}};
      kaliLines.splice(0, kaliLines.length, "ubuntu@kali:~$ sqlmap -u x --batch", "[*] ending @ 10:00:00", "ubuntu@kali:~$ sqlmap -u x --batch", "[INFO] testing");
      await frames();
      return {{idle, done, again: shown('coach-ring'), gone: shown('step-coach')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["idle"] == {"shown": True, "top": 96}, "the prompt line is rung before the run"
    assert result["done"] == {"text": "The run has finished. Press Check.", "shown": True, "floating": False, "below": True,
                              "ring": {"left": 1054, "top": 399, "width": 142, "height": 30}, "dim": False}, (
        "the line sits right under the button inside the note, never floating over the run card")
    assert result["again"] is False, "a new command after the finished run leaves nothing to ring until its output ends"
    assert result["gone"] is False

def test_a_sidebar_step_rings_the_top_values_once_the_popover_shows_that_field_s_name(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      const doc = browser.element('pane-frame').contentDocument;
      const plain = doc.querySelector;
      let title = 'Top values';
      doc.querySelector = (selector) => (selector === '[data-test-subj="fieldPopoverHeader_fieldDisplayName"]'
        ? {{textContent: title, getBoundingClientRect: () => box(300, 200, 100, 20)}} : plain(selector));
      {to("run_source")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="field-source_ip"]', box(20, 400, 160, 24));
      kibana.set('[data-test-subj="dscFieldStats-topValues"]', box(200, 450, 260, 90));
      await frames();
      const before = styled('coach-ring').top;
      title = 'source_ip';
      await frames();
      return {{before, after: styled('coach-ring').top}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"before": 495, "after": 540}, "the popover header holds the field name, not the text Top values"

def test_a_step_that_keeps_the_document_open_does_not_close_the_flyout_on_arrival(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      const doc = browser.element('pane-frame').contentDocument;
      const plain = doc.querySelector;
      let closed = 0;
      doc.readyState = 'complete';
      doc.querySelector = (selector) => {{
        if (selector === '[data-test-subj="queryInput"]') return {{value: '', getBoundingClientRect: () => box(300, 100, 400, 36)}};
        if (selector === '[data-test-subj="euiFlyoutCloseButton"]') return {{click: () => {{ closed += 1; }}}};
        return plain(selector);
      }};
      {to("rule")}
      await browser.click('step-open');
      await frames(3);
      const leaving = closed;
      {to("kept")}
      await frames(3);
      return {{leaving, kept: closed}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"leaving": 1, "kept": 1}

def test_a_hit_count_step_asks_for_the_query_until_it_changes_whether_the_previous_result_was_empty_or_not(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.kibana.none'] = 'No events match.';
      STRINGS.en['lesson.kibana.query'] = 'Type the KQL here.';
      STRINGS.en['lesson.demo.callout.logged'] = 'The count.';
      const doc = browser.element('pane-frame').contentDocument;
      const plain = doc.querySelector;
      const input = {{value: 'status : 500', getBoundingClientRect: () => box(300, 100, 400, 36)}};
      doc.querySelector = (selector) => (selector === '[data-test-subj="queryInput"]' ? input : plain(selector));
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="discoverQueryHits"]', box(400, 150, 80, 20));
      await frames();
      const previous = browser.text('coach-callout');
      input.value = 'status : 200';
      await frames();
      const counted = browser.text('coach-callout');
      input.value = 'status : 500';
      kibana.delete('[data-test-subj="discoverQueryHits"]');
      kibana.set('[data-test-subj="discoverNoResults"]', box(400, 300, 300, 40));
      await frames();
      const arrival = {{text: browser.text('coach-callout'), ring: styled('coach-ring').top}};
      input.value = 'url : *nothing*';
      await frames();
      return {{previous, counted, arrival, none: browser.text('coach-callout'), ring: styled('coach-ring').top}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["previous"] == "Type the KQL here.", "the previous query's count is not this step's answer either"
    assert result["counted"] == "The count."
    assert result["arrival"] == {"text": "Type the KQL here.", "ring": 190}, (
        "the previous step's empty result is not this step's answer: the query bar is rung first")
    assert result["none"] == "No events match." and result["ring"] == 390

def test_a_terminal_step_rings_the_prompt_until_its_line_appears(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.term.prompt'] = 'Type the command here.';
      STRINGS.en['lesson.demo.callout.verdict'] = 'The verdict';
      {to("verdict")}
      await browser.click('step-open');
      await frames();
      const idle = {{ring: styled('coach-ring'), text: browser.text('coach-callout')}};
      kaliLines.splice(0, kaliLines.length, "ubuntu@kali:~$ sqlmap -u x", "[INFO] not injectable", "ubuntu@kali:~$ ");
      await frames();
      return {{idle, found: {{ring: styled('coach-ring'), text: browser.text('coach-callout')}}}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["idle"]["text"] == "Type the command here." and result["idle"]["ring"]["top"] == 96
    assert result["found"]["text"] == "The verdict" and result["found"]["ring"]["top"] == 116

def test_a_closed_pane_rings_the_open_button_with_its_own_callout_a_solo_step_has_no_ring_and_a_note_target_has_no_pane_button(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.open.callout'] = 'Open it here first.';
      placeAt('step-open', box(1060, 300, 120, 28));
      {to("search")}
      await frames();
      const opener = browser.element('step-open');
      const line = browser.element('step-coach');
      const closed = {{ring: styled('coach-ring'), ringShown: shown('coach-ring'), dim: shown('coach-dim'),
                       callout: shown('step-coach') ? browser.text('step-coach') : null, floating: shown('coach-callout'),
                       below: line.parentNode.children[line.parentNode.children.indexOf(opener) + 1] === line}};
      await browser.click('[data-pane="elk"]');
      {to("db_ip")}
      await frames(3);
      const solo = {{button: shown('step-open'), ring: shown('coach-ring'), callout: shown('coach-callout')}};
      {to("cost")}
      await frames();
      return {{closed, solo, button: shown('step-open'), ringShown: shown('coach-ring')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["closed"]["ring"] == {"left": 1054, "top": 299, "width": 132, "height": 30}
    assert (result["closed"]["ringShown"], result["closed"]["dim"], result["closed"]["callout"]) == (
        True, False, "Open it here first.")
    assert (result["closed"]["floating"], result["closed"]["below"]) == (False, True), (
        "the line follows the button inside the note and never floats over the task text")
    assert result["solo"] == {"button": True, "ring": False, "callout": False}, "the last step keeps the button and gets no ring"
    assert result["button"] is False, "the objectives card is on screen whichever pane is open"

def test_an_address_bar_target_inside_the_pane_still_gets_its_callout(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.address'] = 'Type the address here.';
      placeAt('site-address', box(120, 60, 800, 28));
      {to("address")}
      await browser.click('step-open');
      await frames();
      const spot = callout();
      return {{shown: shown('coach-callout'), below: spot && spot.top > 88, left: spot && spot.left,
               meets: meets(spot, {{left: 120, top: 60, width: 800, height: 28}})}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"shown": True, "below": True, "left": 120, "meets": False}, (
        "below the bar at its left end, clear of the page's own search box in the middle")

def test_a_map_callout_stays_beside_its_target_and_off_the_map_text(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.board_ip'] = 'The board address.';
      await frames();
      window.dispatchEvent({{type: 'message', data: {{map: 'drawn'}}, source: browser.element('topology-frame').contentWindow}});
      await frames();
      const last = posted.filter((one) => one.frame === 'map' && one.data.locate).pop();
      const text = [{{x: 560, y: 262, w: 70, h: 40}}, {{x: 640, y: 250, w: 60, h: 24}}];
      window.dispatchEvent({{type: 'message', data: {{located: last.data.id, rect: {{x: 400, y: 300, w: 90, h: 16}}, zones: [], text}},
                             source: browser.element('topology-frame').contentWindow, origin: last.origin}});
      await frames();
      const spot = callout();
      const placed = text.map((one) => ({{left: 60 + one.x, top: 96 + one.y, width: one.w, height: one.h}}));
      return {{spot, near: Math.abs(spot.left - 460) < 400 && Math.abs(spot.top - 396) < 120, over: placed.some((one) => meets(spot, one))}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["near"] is True, "beside the ring, not in a corner of the map"
    assert result["over"] is False

def test_the_course_summary_shows_the_learner_s_own_two_scores(client):
    seen = open_page(client, "/blue/1/", setup=served(next_lesson=None), scenario=f"""
      STRINGS.en['lesson.course.values'] = 'S1 {{0}} / attacks {{1}} caught {{2}} / benign {{3}} alerted {{4}}';
      {to("db_ip")}
      {answering(RIGHT["db_ip"])}
      await browser.wait(500);
      const line = document.querySelector('#step-act [data-act="values"]');
      return {{text: line.textContent, hidden: line.classList.contains('hidden')}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"text": "S1 10 / attacks 2 caught 1 / benign 3 alerted 1", "hidden": False}, (
        "score 1 counts each lost objective's difficulty, doubled when undetected: 3 x 2 + 4 x 1"
    )

def test_a_developer_tools_callout_keeps_off_the_sibling_tabs_and_the_other_requests(client):
    seen = open_page(client, "/blue/1/", setup=served() + DEV, scenario=f"""
      STRINGS.en['lesson.dev.tab.headers'] = 'Press this tab';
      {to("method")}
      await browser.click('step-open');
      browser.element('site-dev-toggle').setAttribute('aria-pressed', 'true');
      listRows('true');
      showTabs('tab.payload');
      await frames();
      const spot = callout();
      const others = [...document.querySelectorAll('[data-coach="row"], [data-coach="tab.payload"], [data-coach="general.method"], [data-coach="payload.query"]')]
        .map((one) => RECTS.get(one));
      return {{text: browser.text('coach-callout'), spot, over: others.some((one) => meets(spot, one))}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["text"] == "Press this tab" and seen["result"]["spot"] is not None
    assert seen["result"]["over"] is False

def test_a_hit_count_callout_keeps_off_the_toolbar_buttons_beside_the_count(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.logged'] = 'The count of the results shown, and more words so it is long.';
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="discoverQueryHits"]', box(400, 150, 80, 20));
      kibana.set('[data-test-subj="dscViewModeFieldStatsButton"]', box(500, 146, 108, 28));
      kibana.set('[data-test-subj="dataGridColumnSelectorButton"]', box(620, 146, 116, 28));
      await frames();
      const spot = callout();
      return {{spot, over: [[560, 242, 108, 28], [680, 242, 116, 28]].map(([left, top, width, height]) => meets(spot, {{left, top, width, height}}))}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["spot"] is not None and seen["result"]["over"] == [False, False]

def test_a_callout_beside_a_website_target_that_is_boxed_in_sits_on_the_nearest_free_row_centred_on_the_target(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.sort'] = 'The sort menu.';
      {to("sort")}
      await browser.click('step-open');
      await frames();
      answer('site-frame', {{x: 700, y: 300, w: 120, h: 30}}, [
        {{x: 60, y: 340, w: 900, h: 30}}, {{x: 60, y: 260, w: 900, h: 30}}, {{x: 60, y: 300, w: 600, h: 30}},
        {{x: 840, y: 300, w: 100, h: 30}}]);
      await frames();
      const spot = callout();
      const target = {{left: 760, top: 396, width: 120, height: 30}};
      return {{spot, centred: Math.abs(spot.left + 110 - (target.left + 60)) < 40, near: Math.abs(spot.top - target.top) < 90}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["spot"] is not None
    assert seen["result"]["centred"] is True and seen["result"]["near"] is True, (
        "not left-aligned after the row's text with a long leader across the page")

RULES = """
const rules = {content: 'alert http any any -> any any (msg:"one"; sid:1; rev:1;)\\n', version: "v1"};
const serveAll = browser.serve;
browser.serve = (handler) => serveAll((request) => (request.route.startsWith('/api/rules/') ? {body: rules} : handler(request)));
globalThis.getComputedStyle = globalThis.getComputedStyle || (() => ({font: '11px monospace'}));
const createElement = document.createElement;
document.createElement = (tag) => (tag === 'canvas' ? {getContext: () => ({measureText: () => ({width: 100})})} : createElement.call(document, tag));
"""

def test_the_rules_step_rings_the_editor_s_last_line_until_the_text_changes_then_the_apply_button_off_the_editor(client):
    seen = open_page(client, "/blue/1/", setup=RULES + served(), scenario=f"""
      STRINGS.en['lesson.rules.add_line'] = 'Add one rule line here.';
      STRINGS.en['lesson.rules.press_apply'] = 'Press Apply';
      {to("write")}
      await frames(4);
      const editor = box(1060, 500, 340, 160);
      Object.assign(browser.element('lesson-rules-text'), {{clientHeight: 160, clientWidth: 340}});
      placeAt('lesson-rules-text', editor);
      placeAt('lesson-rules', box(1050, 440, 380, 280));
      placeAt('lesson-rules-apply', box(1060, 680, 60, 28));
      const area = browser.element('lesson-rules-text');
      await frames(2);
      const adding = {{text: browser.text('coach-callout'), ring: styled('coach-ring'), spot: callout()}};
      area.value += 'alert http any any -> any any (msg:"two"; sid:9000001; rev:1;)';
      area.selectionStart = area.selectionEnd = area.value.length;
      area.dispatchEvent({{type: 'input'}});
      await frames(2);
      const applying = {{text: browser.text('coach-callout'), ring: styled('coach-ring'), spot: callout()}};
      return {{adding, applying, over: meets(applying.spot, editor), addingOver: meets(adding.spot, {{left: 1060, top: 500, width: 340, height: 16}})}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["adding"]["text"] == "Add one rule line here."
    assert result["adding"]["ring"]["top"] == 500 + 8 + 1 + 16 - 1, "the last line of the loaded rules, not the Apply button"
    assert result["addingOver"] is False
    assert result["applying"]["text"] == "Press Apply" and result["applying"]["ring"]["top"] == 680 - 6
    assert result["over"] is False, "the callout sits beside the Apply button, never over the rules being edited"

def test_the_rules_ring_and_scroll_follow_the_rows_a_long_line_wraps_into(client):
    seen = open_page(client, "/blue/1/", setup=RULES + served(), scenario=f"""
      const plain = document.createElement;
      document.createElement = (tag) => {{
        const made = plain(tag);
        if (tag === 'div') Object.defineProperty(made, 'offsetHeight', {{get: () => 16 * Math.ceil(Math.max(1, made.textContent.length) / Math.floor(parseFloat(made.parentNode.style.width) / 8))}});
        return made;
      }};
      {to("write")}
      await frames(4);
      const area = browser.element('lesson-rules-text');
      Object.assign(area, {{clientHeight: 60, clientWidth: 256, value: ['x'.repeat(80), 'y'.repeat(20), 'z'.repeat(70)].join('\\n')}});
      placeAt('lesson-rules-text', box(1060, 500, 260, 200));
      return {{
        first: ruleLineRect(0), second: ruleLineRect(1), third: ruleLineRect(2),
        past: ruleLineRect(3),
        scrolled: (ruleLineShown(2), area.scrollTop),
        kept: (area.scrollTop = 0, ruleLineShown(0), area.scrollTop),
        wide: (area.scrollTop = 0, area.clientWidth = 700, ruleLineRect(2)),
      }};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert [result[name]["top"] for name in ("first", "second", "third", "past")] == [509, 557, 573, 621]
    assert [result[name]["height"] for name in ("first", "second", "third", "past")] == [48, 16, 48, 16]
    assert result["scrolled"] == 66, "the three-row line is centred in the 60px window by its own height, not by one row"
    assert result["kept"] == 0
    assert result["wide"]["top"] == 509 + 16 + 16 and result["wide"]["height"] == 16, "wide enough, the same lines take one row each"

def lesson_steps(lesson_id):
    return {one["id"]: one for one in next(one for one in wargames.foundations("board") if one["id"] == lesson_id)["steps"]}

def test_f2_reads_the_request_panel_top_down_search_method_path_status_parameter_sort_missing():
    assert list(lesson_steps("f2")) == ["search", "method", "path", "status", "parameter", "sort", "missing"]

def test_f6_rings_the_waf_prompt_until_the_exception_line_prints_and_the_cost_step_points_at_the_note_card_only():
    steps = lesson_steps("f6")

    assert steps["excluded"]["point"]["term"] == {"pane": "waf", "match": "ctl:ruleRemove", "idle": r"\$ "}
    assert "panel" in steps["cost"]["point"] and "kibana" not in steps["cost"]["point"]

def test_the_console_is_told_which_leg_a_log_question_is_about(client):
    from tests.test_foundations import opened as opened_lesson

    session = opened_lesson("f3")
    shown = {one["id"]: one for one in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert [shown[name]["check"].get("leg") for name in ("site_source", "client_source", "xff")] == ["upstream", "inbound", "upstream"]

def test_a_callout_for_a_row_of_the_objectives_card_sits_on_the_card_s_title_line_not_over_the_next_card(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.cost'] = 'The total is here';
      placeAt('lesson-objectives', box(1050, 240, 380, 160));
      {to("cost")}
      await frames();
      return {{callout: callout()}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["callout"]["top"] == 246, "inside the card, on its title line, clear of the ring"

def test_the_map_waits_for_a_fit_only_when_the_pane_opens_at_a_size_it_was_not_fitted_to_and_the_ring_waits_with_it(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      const frameWindow = browser.element('topology-frame').contentWindow;
      const said = (what) => window.dispatchEvent({{type: 'message', data: {{map: what}}, source: frameWindow}});
      await browser.click('[data-pane="topology"]');
      const loading = shown('map-wait');
      said('drawn');
      const drawn = shown('map-wait');
      await browser.click('[data-pane="elk"]');
      await browser.click('[data-pane="topology"]');
      const reopened = shown('map-wait');
      await browser.click('[data-pane="elk"]');
      placeAt('topology-frame', box(60, 96, 700, 704));
      await browser.click('[data-pane="topology"]');
      const resized = shown('map-wait');
      said('fitted');
      return {{loading, drawn, reopened, resized, fitted: shown('map-wait')}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"loading": True, "drawn": False, "reopened": False, "resized": True, "fitted": False}

def test_a_replay_step_lists_which_of_its_two_requests_is_confirmed_while_it_checks_on_its_own(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.replay.attack'] = 'Attack: {{0}}';
      STRINGS.en['lesson.demo.replay.benign'] = 'Normal: {{0}}';
      {to("replay")}
      const first = browser.text('step-status');
      range.attacked = true;
      for (let i = 0; i < 6; i += 1) await browser.wait(1000);
      const second = browser.text('step-status');
      range.passed = true;
      for (let i = 0; i < 6; i += 1) await browser.wait(1000);
      return {{first, second, third: browser.text('step-status'), shown: shown('step-status')}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["first"] == "Attack: waiting\nNormal: waiting"
    assert seen["result"]["second"] == "Attack: confirmed\nNormal: waiting"
    assert seen["result"]["shown"] is False, "the pass line takes over once both are confirmed"

def test_a_sidebar_step_that_shows_the_top_values_says_what_they_are_and_stays_off_the_toolbar(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.kibana.top_values'] = 'The most frequent values.';
      STRINGS.en['lesson.demo.callout.run_source'] = 'Press the field name.';
      const doc = browser.element('pane-frame').contentDocument;
      const plain = doc.querySelector;
      let title = 'Top values';
      doc.querySelector = (selector) => (selector === '[data-test-subj="fieldPopoverHeader_fieldDisplayName"]'
        ? {{textContent: title, getBoundingClientRect: () => box(300, 200, 100, 20)}} : plain(selector));
      {to("run_source")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="field-source_ip"]', box(20, 400, 160, 24));
      kibana.set('[data-test-subj="dscFieldStats-topValues"]', box(200, 450, 260, 30));
      kibana.set('[data-test-subj="dataGridColumnSelectorButton"]', box(470, 446, 116, 28));
      await frames();
      const before = browser.text('coach-callout');
      title = 'source_ip';
      await frames();
      const spot = callout();
      return {{before, after: browser.text('coach-callout'), over: meets(spot, {{left: 530, top: 542, width: 116, height: 28}})}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["before"] == "Press the field name."
    assert seen["result"]["after"] == "The most frequent values."
    assert seen["result"]["over"] is False

def test_the_query_prompt_keeps_off_the_time_range_picker_the_step_asks_to_leave_unchanged(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.kibana.query'] = 'Type the KQL here.';
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="queryInput"]', box(200, 100, 400, 36));
      kibana.set('[data-test-subj="discoverQueryHits"]', box(400, 150, 80, 20));
      kibana.set('[data-test-subj="superDatePickerToggleQuickMenuButton"]', box(610, 100, 36, 36));
      kibana.set('[data-test-subj="superDatePickerstartDatePopoverButton"]', box(650, 100, 150, 36));
      await frames();
      const spot = callout();
      return {{text: browser.text('coach-callout'), over: [[670, 196, 36, 36], [710, 196, 150, 36]].map(([left, top, width, height]) =>
        meets(spot, {{left, top, width, height}}))}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["text"] == "Type the KQL here."
    assert seen["result"]["over"] == [False, False]

def test_a_map_callout_that_finds_no_spot_beside_its_label_goes_to_the_nearest_free_row_and_not_to_a_corner(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.board_ip'] = 'The board address.';
      await frames();
      window.dispatchEvent({{type: 'message', data: {{map: 'drawn'}}, source: browser.element('topology-frame').contentWindow}});
      await frames();
      const last = posted.filter((one) => one.frame === 'map' && one.data.locate).pop();
      const text = [{{x: 510, y: 294, w: 220, h: 28}}, {{x: 160, y: 294, w: 220, h: 28}},
                    {{x: 335, y: 336, w: 220, h: 28}}, {{x: 335, y: 252, w: 220, h: 28}}];
      window.dispatchEvent({{type: 'message', data: {{located: last.data.id, rect: {{x: 400, y: 300, w: 90, h: 16}}, zones: [], text}},
                             source: browser.element('topology-frame').contentWindow, origin: last.origin}});
      await frames();
      const spot = callout();
      return {{spot, apart: Math.hypot(spot.left + 110 - 505, spot.top + 14 - 404)}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["spot"] is not None and seen["result"]["apart"] < 300

def test_a_map_zone_callout_goes_inside_the_zone_on_the_first_row_free_of_text(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.path'] = 'The internet side.';
      {to("path")}
      await frames();
      window.dispatchEvent({{type: 'message', data: {{map: 'drawn'}}, source: browser.element('topology-frame').contentWindow}});
      await frames();
      const last = posted.filter((one) => one.frame === 'map' && one.data.locate).pop();
      const caption = {{x: 120, y: 40, w: 160, h: 20}};
      window.dispatchEvent({{type: 'message', data: {{located: last.data.id, rect: {{x: 100, y: 20, w: 700, h: 600}}, zones: [], text: [caption]}},
                             source: browser.element('topology-frame').contentWindow, origin: last.origin}});
      await frames();
      const spot = callout();
      const zone = {{left: 160, top: 116, width: 700, height: 600}};
      return {{spot, inside: spot.left >= zone.left && spot.top >= zone.top && spot.left + spot.width <= zone.left + zone.width,
              belowCaption: spot.top >= 96 + 60}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["inside"] is True and seen["result"]["belowCaption"] is True

def test_the_terminal_is_fitted_to_the_pane_it_sits_in_and_left_alone_once_it_fits(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      const resized = [];
      const term = browser.element('kali-frame').contentWindow.term;
      const grid = {{getBoundingClientRect: () => box(0, 0, term.cols * 12, term.rows * 20)}};
      term.element = {{querySelector: (selector) => (selector === '.xterm-screen' ? grid : null),
                      parentElement: {{clientWidth: 1000, clientHeight: 480}}}};
      term.resize = (cols, rows) => {{ resized.push([cols, rows]); term.cols = cols; term.rows = rows; }};
      await browser.click('[data-pane="kali"]');
      for (let i = 0; i < 4; i += 1) await browser.wait(500);
      return {{resized}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["resized"] == [[83, 24]]

def test_the_map_pane_keeps_its_size_while_another_pane_is_open(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      await browser.click('[data-pane="topology"]');
      const open = browser.element('topology').style.visibility;
      await browser.click('[data-pane="elk"]');
      const closed = browser.element('topology').style.visibility;
      return {{open, closed, display: browser.element('topology').style.display || ''}};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"open": "", "closed": "hidden", "display": ""}

def test_a_callout_for_the_objectives_card_leaves_the_title_line_when_its_leader_would_cross_a_column_header(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      STRINGS.en['lesson.demo.callout.cost'] = 'The total is here';
      placeAt('lesson-objectives', box(1050, 240, 380, 160));
      placeAt('lesson-objectives-total', box(1380, 360, 40, 20));
      {to("cost")}
      await frames();
      const heading = callout();
      RECTS.set(document.querySelectorAll('#lesson-objectives-head th')[2], box(1340, 280, 80, 16));
      await frames();
      return {{heading, moved: callout()}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["heading"]["top"] == 246
    assert seen["result"]["moved"]["top"] >= 400, "below the card, where the leader crosses no header"

def test_a_developer_tools_callout_also_keeps_off_the_toolbar_controls_and_the_tabs_it_does_not_point_at(client):
    seen = open_page(client, "/blue/1/", setup=served() + DEV, scenario=f"""
      STRINGS.en['lesson.dev.tab.headers'] = 'Press this tab';
      {to("method")}
      await browser.click('step-open');
      browser.element('site-dev-toggle').setAttribute('aria-pressed', 'true');
      listRows('true');
      showTabs('tab.payload');
      await frames();
      const first = callout();
      RECTS.set(browser.element('site-dev-throttle'), {{...first, right: first.left + first.width, bottom: first.top + first.height}});
      await frames();
      const second = callout();
      return {{first, second, over: meets(first, second)}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["second"] is not None and seen["result"]["over"] is False
