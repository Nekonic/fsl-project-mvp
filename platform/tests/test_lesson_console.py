import json
import re

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

STEPS = steps_of()
IDS = ids()

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
const own = (id) => (range.progress[id] = range.progress[id] || {hint: 0, done_for_me: false, wrong: 0, passed: null, skipped: null});
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
  if (stepped) {
    const id = stepped[1];
    own(id).done_for_me = true;
    used({step: id, level: "do"});
    const check = FULL[id];
    if (check.kind === "answer" || check.kind === "choice") return {body: judge(id, {answer: RIGHT[id]})};
    if (check.kind === "click" || check.kind === "sent") return {body: judge(id, {})};
    return {body: passing(id)};
  }
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
    if (request.body.level === "hint") own(request.body.step).hint = Math.min(4, own(request.body.step).hint + 1);
    else own(request.body.step).done_for_me = true;
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

def test_a_guided_session_shows_the_note_as_a_pill_and_an_unguided_one_shows_nothing(client):
    shown = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      return {
        note: browser.element('lesson').classList.contains('hidden'),
        pill: browser.element('note-pill').classList.contains('hidden'),
        pillText: browser.text('note-pill-text'),
        paragraphs: browser.text('lesson-steps'),
        frame: browser.element('pane-frame').getAttribute('src'),
      };
    """)
    plain = open_page(client, "/blue/1/", setup=guided(False), scenario="""
      return {note: browser.element('lesson').classList.contains('hidden'),
              pill: browser.element('note-pill').classList.contains('hidden'),
              routes: browser.requests.map((r) => r.route)};
    """)

    assert shown["errors"] == [] and plain["errors"] == []
    assert (shown["result"]["note"], shown["result"]["pill"]) == (True, False), (
        "the note starts folded to a pill so the tool keeps the screen"
    )
    assert shown["result"]["pillText"] == english("lesson.note.pill", 1, len(STEPS))
    assert english("lesson.logs.read") in shown["result"]["paragraphs"]
    assert shown["result"]["frame"] == "/kibana/app/discover#/", "Kibana stays the pane under the note"
    assert (plain["result"]["note"], plain["result"]["pill"]) == (True, True)
    assert "/api/sessions/1/waf/" not in plain["result"]["routes"]

def test_the_pill_opens_the_note_and_fold_returns_it_to_the_pill_and_both_are_remembered(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      const state = () => ({note: !browser.element('lesson').classList.contains('hidden'),
                            pill: !browser.element('note-pill').classList.contains('hidden'),
                            kept: JSON.parse(localStorage.getItem('fsl-lesson-note') || 'null')});
      await browser.click('note-pill');
      const opened = state();
      await browser.click('lesson-collapse');
      return {opened, folded: state(), label: browser.text('lesson-collapse')};
    """)

    assert seen["result"]["opened"] == {"note": True, "pill": False, "kept": {"tab": "steps"}}
    assert seen["result"]["folded"] == {"note": False, "pill": True, "kept": {"tab": "steps"}}
    assert seen["result"]["label"] == english("lesson.note.collapse")

def test_the_note_has_steps_goal_theory_and_hints_tabs_and_shows_one_at_a_time(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('note-pill');
      const shown = () => [...document.querySelectorAll('[data-pane-of]')]
        .filter((pane) => !pane.classList.contains('hidden')).map((pane) => pane.dataset.paneOf);
      const tabs = [...document.querySelectorAll('#lesson-tabs .tab')].map((tab) => tab.dataset.tab);
      const first = shown();
      await browser.click('[data-tab="hint"]');
      const hint = {shown: shown(), selected: document.querySelector('[data-tab="hint"]').getAttribute('aria-selected')};
      return {tabs, first, hint, kept: JSON.parse(localStorage.getItem('fsl-lesson-note')).tab};
    """)

    assert seen["result"]["tabs"] == ["steps", "goal", "theory", "hint"]
    assert seen["result"]["first"] == ["steps"]
    assert seen["result"]["hint"] == {"shown": ["hint"], "selected": "true"}
    assert seen["result"]["kept"] == "hint"

def test_the_note_starts_folded_on_every_visit_and_reopens_at_the_remembered_tab(client):
    seen = open_page(client, "/blue/1/", setup=guided(True) + """
      localStorage.setItem('fsl-lesson-note', JSON.stringify({open: true, tab: 'theory'}));
    """, scenario="""
      const folded = browser.element('lesson').classList.contains('hidden');
      await browser.click('note-pill');
      return {folded, theory: document.querySelector('[data-pane-of="theory"]').classList.contains('hidden')};
    """)

    assert seen["result"] == {"folded": True, "theory": False}, (
        "an open note from an earlier visit must not take a quarter of the screen on load"
    )

def test_the_note_floats_over_the_pane_in_the_empty_part_of_kibana_s_header_and_reserves_no_column(client):
    page = client.get("/blue/1/").content.decode()
    note = re.search(r'<aside id="lesson" class="([^"]+)"', page).group(1).split()
    pill = re.search(r'<button id="note-pill" class="([^"]+)"', page).group(1).split()

    assert {"absolute", "top-2", "right-4", "w-[360px]"} <= set(note), note
    assert {"absolute", "top-2", "right-28"} <= set(pill), pill

def test_the_hints_tab_holds_reasoning_and_folds_the_full_solution_until_asked(client):
    command = commands("f6")["excluded"]
    seen = open_page(client, "/blue/1/", setup=guided(True, "f6") + """
      localStorage.setItem('fsl-lesson-step-1', '2');
    """, scenario=f"""
      const hidden = () => browser.element('lesson-answer-box').classList.contains('hidden');
      const cards = [...browser.element('lesson-hints').querySelectorAll('[data-card]')].map((c) => c.dataset.card);
      const folded = hidden();
      await browser.click('lesson-answer-toggle');
      const unreached = browser.text('lesson-answer');
      await browser.click('[data-step="{ids("f6").index("excluded")}"]');
      await browser.wait(16);
      return {{cards, folded, opened: !hidden(), unreached, answer: browser.text('lesson-answer'),
              hints: browser.text('lesson-hints'),
              form: ['lesson-paranoia', 'lesson-exclusions', 'lesson-save'].map((id) => document.getElementById(id)),
              writes: browser.requests.filter((r) => r.method !== 'GET' && !r.route.startsWith('/api/sessions/1/lesson/steps/')).map((r) => r.route)}};
    """)

    assert seen["result"]["cards"] == ["why_leak"]
    assert english("lesson.miss.hint.why_leak.title") in seen["result"]["hints"]
    assert command not in seen["result"]["hints"], "a hint says why, the steps say what to type"
    assert seen["result"]["folded"] is True and seen["result"]["opened"] is True
    assert command not in seen["result"]["unreached"], "a step's command reaches the browser once the step is reached"
    assert seen["result"]["answer"] == command
    assert seen["result"]["form"] == [None, None, None], "the WAF is read in the WAF terminal"
    assert seen["result"]["writes"] == []

CATALOGUE_DECLARING = """
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

CATALOGUE = CATALOGUE_DECLARING.replace("DECLARED", '"minimal"')

def test_only_a_wargame_with_foundations_offers_one_and_it_opens_a_guided_session_on_its_defense(client):
    seen = open_page(client, "/", setup=CATALOGUE, scenario="""
      const lessons = [...document.querySelectorAll('[data-lesson]')].map((b) => b.dataset.wargame);
      await browser.click('[data-lesson="true"]');
      return {lessons, posted: browser.requests.filter((r) => r.method === 'POST' && r.route !== '/api/sessions/1/ingest/').map((r) => r.body)};
    """)

    assert seen["errors"] == []
    assert seen["result"]["lessons"] == ["board"], "corp declares no foundation"
    assert seen["result"]["posted"] == [{"scenario": "board", "guidance": True, "lesson": "f1", "defense": "minimal"}]

def test_starting_a_foundation_sends_the_defense_it_declares_not_a_fixed_one(client):
    seen = open_page(client, "/", setup=CATALOGUE_DECLARING.replace("DECLARED", '"full"'), scenario="""
      await browser.click('[data-lesson="true"]');
      return browser.requests.filter((r) => r.method === 'POST').map((r) => r.body);
    """)

    assert seen["result"] == [{"scenario": "board", "guidance": True, "lesson": "f1", "defense": "full"}]

def test_the_goal_line_is_pinned_above_the_tabs_whichever_tab_is_open(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('note-pill');
      await browser.click('[data-tab="theory"]');
      return {text: browser.text('lesson-goal-line'), hidden: browser.element('lesson-goal-line').classList.contains('hidden')};
    """)
    page = client.get("/blue/1/").content.decode()

    assert seen["result"] == {"text": english("lesson.logs.summary"), "hidden": False}
    assert page.index('id="lesson-goal-line"') < page.index('id="lesson-tabs"') < page.index('data-pane-of="steps"'), (
        "the goal sits above the tabs, outside every tab's pane"
    )

def test_the_catalogue_says_which_wargame_carries_foundations(client):
    listed = {w["id"]: [unit["id"] for unit in w["foundations"]] for w in client.get("/api/wargames/").json()}

    assert listed == {"board": ["f1", "f2", "f3", "f4", "f5", "f6"], "corp": []}

EXPAND = '[data-test-subj="docTableExpandToggleColumn"]'

COACHED = """
Object.getPrototypeOf(document.body).getBoundingClientRect =
  () => ({left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0});
const pane = browser.element('pane-frame');
pane.getBoundingClientRect = () => ({left: 200, top: 50, right: 1000, bottom: 650, width: 800, height: 600});
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

SUBMIT = """
      const submit = async (value) => {
        document.querySelector('#coach-pop-act [data-act="value"]').value = value;
        document.querySelector('#coach-pop-act [data-act="answer"]').dispatchEvent({type: 'submit', preventDefault() {}});
        await browser.settle();
        return browser.text('coach-pop-said');
      };
"""

def test_the_logs_foundation_is_six_steps_each_checked_by_the_platform():
    assert IDS == ["search", "engine", "probe", "find", "verdict", "address"]
    assert [step["check"]["kind"] for step in STEPS] == ["sent", "choice", "sent", "click", "answer", "answer"]

def test_the_coach_boxes_its_target_as_soon_as_the_step_shows_it(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("find")}
      present.add({EXPAND!r});
      await browser.wait(16);
      const box = () => browser.element('coach-box');
      const shown = {{hidden: box().classList.contains('hidden'), left: box().style.left,
              top: box().style.top, width: box().style.width, layer: box().style.zIndex,
              events: box().style.pointerEvents}};
      {hints(2)}
      return {{shown, help: browser.text('coach-pop-help')}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["shown"] == {
        "hidden": False, "left": "206px", "top": "66px", "width": "108px", "layer": "30", "events": "none",
    }, "the box sits over the element, offset by where the Kibana pane is, and never takes a click"
    assert english("lesson.logs.nudge.find") in seen["result"]["help"]
    assert english("lesson.hint.point") in seen["result"]["help"]

def test_the_popover_names_the_step_says_what_to_do_and_shows_the_progress(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      await browser.wait(16);
      return {hidden: browser.element('coach-pop').classList.contains('hidden'),
              count: browser.text('coach-pop-count'), title: browser.text('coach-pop-title'),
              text: browser.text('coach-pop-text'),
              command: browser.element('coach-pop-command').classList.contains('hidden'),
              status: browser.text('coach-pop-status'), checkButton: document.getElementById('coach-pop-check'),
              dots: browser.element('coach-pop-dots').querySelectorAll('.dot').length,
              lit: browser.element('coach-pop-dots').querySelectorAll('.dot-blue').length,
              buttons: [browser.text('coach-pop-back'), browser.text('coach-pop-next')],
              back: browser.element('coach-pop-back').disabled};
    """)

    assert seen["result"] == {
        "hidden": False, "count": f"1 / {len(STEPS)}", "title": english("lesson.logs.label.search"),
        "text": english("lesson.open.site"), "command": True, "status": english("lesson.status.auto"),
        "checkButton": None, "dots": len(STEPS), "lit": 1,
        "buttons": [english("lesson.coach.back"), english("lesson.coach.next")], "back": True,
    }, "checks run by themselves: a status line, no Check button"

def test_the_popover_sits_below_its_target_or_above_it_when_there_is_no_room(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("find")}
      present.add({EXPAND!r});
      await browser.wait(16);
      const pop = browser.element('coach-pop').style;
      const arrow = browser.element('coach-pop-arrow');
      const roomy = {{top: pop.top, arrowTop: arrow.style.top, arrow: arrow.classList.contains('hidden')}};
      pane.getBoundingClientRect = () => ({{left: 200, top: 50, right: 1000, bottom: 900, width: 800, height: 850}});
      table.getBoundingClientRect = () => ({{left: 10, top: 700, right: 110, bottom: 740, width: 100, height: 40}});
      await browser.wait(16);
      return {{roomy, cramped: {{top: pop.top, arrowBottom: arrow.style.bottom}}}};
    """)

    assert seen["result"]["roomy"] == {"top": "124px", "arrowTop": "-6px", "arrow": False}
    assert seen["result"]["cramped"] == {"top": "536px", "arrowBottom": "-6px"}

def test_the_coach_points_at_a_console_control_above_the_note_s_layer_and_leaves_the_note_folded(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f1") + """
      document.querySelector('.pane-tab[data-pane="topology"]').getBoundingClientRect =
        () => ({left: 8, top: 120, right: 52, bottom: 164, width: 44, height: 44});
    """, scenario="""
      await browser.wait(16);
      const box = browser.element('coach-box');
      return {text: browser.text('coach-pop-text'), left: box.style.left, layer: box.style.zIndex,
              target: box.dataset.target, note: browser.element('lesson').classList.contains('hidden')};
    """)

    assert seen["result"] == {
        "text": english("lesson.range.coach.map"), "left": "4px", "layer": "9999",
        "target": '.pane-tab[data-pane="topology"]', "note": True,
    }

def test_the_coach_says_where_to_look_when_the_element_never_appears(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("find")}
      const hidden = () => browser.element('coach-pop-missing').classList.contains('hidden');
      const early = hidden();
      for (let i = 0; i < 130; i += 1) await browser.wait(16);
      return {{early, late: hidden(), pop: browser.element('coach-pop').classList.contains('hidden')}};
    """)

    assert seen["result"] == {"early": True, "late": False, "pop": False}

def test_an_unguided_session_draws_no_coach(client):
    seen = open_page(client, "/blue/1/", setup=coached(False), scenario="""
      await browser.wait(16);
      return [browser.element('coach-box').classList.contains('hidden'),
              browser.element('coach-pop').classList.contains('hidden')];
    """)

    assert seen["errors"] == [] and seen["result"] == [True, True]

CLICKABLE_KIBANA = """
const listeners = [];
pane.contentDocument.addEventListener = (type, listener, capture) => listeners.push({type, listener, capture});
table.contains = (node) => node === table.inner;
table.inner = {};
"""

def test_a_click_step_passes_when_the_learner_opens_the_highlighted_row(client):
    seen = open_page(client, "/blue/1/", setup=coached() + CLICKABLE_KIBANA, scenario=f"""
      {to("find")}
      present.add({EXPAND!r});
      await browser.wait(16);
      const heard = listeners.filter((l) => l.type === 'click' && l.capture === true);
      heard.forEach((l) => l.listener({{target: {{}}}}));
      await browser.wait(1);
      const missed = browser.text('coach-pop-title');
      heard.forEach((l) => l.listener({{target: table.inner}}));
      await browser.wait(1);
      const status = browser.text('coach-pop-status');
      await browser.wait(1500);
      return {{status, missed, after: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'), heard: heard.length}};
    """)

    assert seen["result"]["heard"] == 1, "the guide listens in the Kibana document in the capture phase"
    assert seen["result"]["missed"] == english("lesson.logs.label.find"), "a click elsewhere does not advance"
    assert seen["result"]["after"] == english("lesson.logs.label.verdict")
    assert seen["result"]["said"] == english("lesson.logs.line.find"), "the step's line greets the next step"
    assert seen["result"]["status"] == "✓ " + english("lesson.logs.ok.find"), "the pass is said before moving on"

def test_the_find_step_offers_a_ready_made_filter_that_opens_kibana_narrowed_to_the_request(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      await browser.click('[data-pane="site"]');
      {to("find")}
      const chip = document.querySelector('#coach-pop-act [data-act="chip"]');
      const label = chip.textContent;
      chip.click();
      await browser.settle();
      return {{label, src: browser.element('pane-frame').getAttribute('src'),
              kibana: document.querySelector('[data-pane="elk"]').getAttribute('aria-selected')}};
    """)

    assert seen["result"] == {"label": english("lesson.logs.chip.find"),
                              "src": "/kibana/app/discover#/?narrowed=find", "kibana": "true"}

def test_the_steps_tab_lists_the_steps_with_the_current_one_marked_and_leaves_the_words_to_the_popover(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      await browser.click('note-pill');
      await browser.click('coach-pop-next');
      const listed = [...browser.element('lesson-step-list').querySelectorAll('[data-step]')];
      const steps = document.querySelector('[data-pane-of="steps"]');
      return {listed: listed.length, done: listed[0].textContent.includes('○') && !listed[0].textContent.includes('✓'),
              skipped: listed[0].textContent, count: browser.text('lesson-step-count'),
              current: listed[1].textContent, buttons: steps.querySelectorAll('button:not([data-step])').length,
              repeated: steps.textContent.includes(browser.text('coach-pop-text')),
              shown: browser.element('lesson-coach-show').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert (result["listed"], result["done"]) == (len(STEPS), True), "a step left unpassed is hollow, not ticked"
    assert english("lesson.skipped") in result["skipped"]
    assert result["count"] == english("lesson.steps.passed", 0, len(STEPS))
    assert english("lesson.logs.label.engine") in result["current"]
    assert english("lesson.status.current") in result["current"]
    assert result["repeated"] is False, "the instruction is said once, in the popover"
    assert (result["buttons"], result["shown"]) == (1, True), "no Back or Next of its own; Show the guide only once closed"

def test_a_step_in_the_list_jumps_the_guide_there(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("probe")}
      return browser.text('coach-pop-title');
    """)

    assert seen["result"] == english("lesson.logs.label.probe")

def test_the_step_reached_is_kept_per_session_and_resumed_on_the_next_visit(client):
    seen = open_page(client, "/blue/1/", setup=coached() + f"""
      localStorage.setItem('fsl-lesson-step-1', '{at("probe") + 1}');
    """, scenario="""
      const resumed = browser.text('coach-pop-title');
      await browser.click('coach-pop-next');
      return {resumed, kept: localStorage.getItem('fsl-lesson-step-1')};
    """)

    assert seen["result"] == {"resumed": english("lesson.logs.label.probe"), "kept": str(at("probe") + 2)}

def test_next_and_a_jump_in_the_list_record_a_step_left_unpassed_as_skipped_and_back_does_not(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      await browser.click('coach-pop-next');
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
        ["attack", "reached"], ["attack", "skipped"], ["follow", "reached"], ["follow", "skipped"], ["stopped", "reached"],
        ["rule", "reached"], ["rule", "skipped"], ["sqlmap", "reached"], ["rule", "reached"],
    ], "a passed step moves on without a skip; Back is not a skip"

def test_the_hint_level_a_step_reached_is_resumed_from_the_session(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5") + "own('rule').hint = 1;", scenario=f"""
      {to("rule", "f5")}
      return browser.text('coach-pop-help');
    """)

    assert seen["result"] == english("lesson.attack.nudge.rule"), "the level comes from the session, not from this browser"

def test_closing_the_popover_hides_the_guide_until_the_steps_tab_brings_it_back(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      const hidden = () => [browser.element('coach-pop').classList.contains('hidden'),
                            browser.element('lesson-coach-show').classList.contains('hidden')];
      await browser.click('coach-pop-close');
      await browser.wait(16);
      const closed = hidden();
      await browser.click('lesson-coach-show');
      await browser.wait(16);
      return {closed, back: hidden()};
    """)

    assert seen["result"] == {"closed": [True, False], "back": [False, True]}

def test_a_foundation_note_opens_its_theory_card_from_the_start_and_folds_it_on_a_click(client):
    shown = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      const theory = browser.element('lesson-theory');
      const cards = [...theory.querySelectorAll('[data-card]')];
      const body = theory.querySelector('[data-card-body="records"]');
      const first = {open: !body.classList.contains('hidden'), expanded: cards[0].getAttribute('aria-expanded')};
      await browser.click('[data-card="records"]');
      return {ids: cards.map((card) => card.dataset.card), first, folded: body.classList.contains('hidden'),
              text: body.textContent};
    """)

    assert shown["errors"] == []
    assert shown["result"]["ids"] == ["records"]
    assert shown["result"]["first"] == {"open": True, "expanded": "true"}, "a foundation teaches its idea first"
    assert shown["result"]["folded"] is True
    assert english("lesson.logs.theory.records.body").split("\n")[0] in shown["result"]["text"]

def test_a_theory_card_points_the_coach_at_what_it_talks_about(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      const before = browser.text('coach-pop-title');
      await browser.click('[data-shows="engine"]');
      return {before, records: browser.text('coach-pop-title')};
    """)

    assert seen["result"] == {
        "before": english("lesson.logs.label.search"), "records": english("lesson.logs.label.engine"),
    }

def test_the_site_step_points_at_the_website_rail_until_the_site_is_open_then_at_its_address_bar(client):
    seen = open_page(client, "/blue/1/", setup=coached() + """
      document.querySelector('.pane-tab[data-pane="site"]').getBoundingClientRect =
        () => ({left: 8, top: 120, right: 52, bottom: 164, width: 44, height: 44});
      browser.element('site-address').getBoundingClientRect =
        () => (browser.element('site-bar').classList.contains('hidden')
          ? {left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0}
          : {left: 300, top: 60, right: 900, bottom: 88, width: 600, height: 28});
    """, scenario=f"""
      {hints(2)}
      await browser.wait(16);
      const rail = browser.element('coach-box').style.left;
      await browser.click('[data-pane="site"]');
      await browser.wait(16);
      return {{rail, bar: browser.element('coach-box').style.left}};
    """)

    assert seen["result"] == {"rail": "4px", "bar": "296px"}

def test_the_terminal_step_folds_its_command_under_show_command_and_runs_it_with_one_button(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6"), scenario=f"""
      await browser.click('[data-pane="waf"]');
      {to("excluded", "f6")}
      await browser.wait(16);
      const folded = {{code: browser.element('coach-pop-code-box').classList.contains('hidden'),
                      view: browser.text('coach-pop-view'), run: browser.text('coach-pop-run'),
                      does: browser.text('coach-pop-does'), wide: browser.element('coach-pop').classList.contains('pop-wide'),
                      popLeft: browser.element('coach-pop').style.left, popTop: browser.element('coach-pop').style.top}};
      await browser.click('coach-pop-view');
      return {{folded, code: browser.text('coach-pop-code'),
              shown: !browser.element('coach-pop-code-box').classList.contains('hidden'),
              view: browser.text('coach-pop-view')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["folded"] == {
        "code": True, "view": english("lesson.command.show"), "run": english("lesson.run"),
        "does": english("lesson.miss.does.excluded"), "wide": True, "popLeft": "644px", "popTop": "434px",
    }, "the popover sits in the pane's bottom right corner, clear of the terminal output"
    assert result["code"] == commands("f6")["excluded"] and result["shown"] is True
    assert result["view"] == english("lesson.command.hide")

def test_the_copy_button_puts_the_step_s_command_on_the_clipboard(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + """
      const copied = [];
      navigator.clipboard = {writeText: async (text) => { copied.push(text); }};
    """, scenario=f"""
      {to("excluded", "f6")}
      await browser.click('coach-pop-view');
      await browser.click('coach-pop-copy');
      return {{copied, said: browser.text('coach-pop-copy')}};
    """)

    assert seen["result"] == {"copied": [commands("f6")["excluded"]], "said": english("lesson.copied")}

def test_kibana_s_first_visit_callouts_are_marked_seen_before_the_pane_loads(client):
    seen = open_page(client, "/blue/1/", setup=coached(False), scenario="""
      return ['discover:docExplorerUpdateCalloutClosed', 'discover:docExplorerCalloutClosed',
              'data.noDataPopover'].map((key) => localStorage.getItem(key));
    """)

    assert seen["result"] == ["true", "true", "true"]

NOTE_OPEN_AT = """
browser.element('lesson').getBoundingClientRect =
  () => ({left: 620, top: 58, right: 980, bottom: 634, width: 360, height: 576});
"""

def test_nothing_on_the_page_is_dimmed_while_a_step_is_shown(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      const dims = [];
      for (let i = 0; i < {len(STEPS)}; i += 1) {{
        present.add({EXPAND!r});
        {hints(2)}
        await browser.wait(16);
        const box = browser.element('coach-box');
        dims.push(box.classList.contains('scrim') || /9999px/.test(box.style.boxShadow || ''));
        await browser.click('coach-pop-next');
      }}
      return dims;
    """)

    assert seen["result"] == [False] * len(STEPS)

def test_a_popover_for_a_control_under_the_open_note_sits_beside_the_note_not_over_it(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5") + NOTE_OPEN_AT + """
      browser.element('topology-hops').getBoundingClientRect =
        () => ({left: 640, top: 300, right: 720, bottom: 330, width: 80, height: 30});
    """, scenario=f"""
      await browser.click('note-pill');
      await browser.click('[data-pane="topology"]');
      {to("stopped", "f5")}
      await browser.wait(16);
      const pop = browser.element('coach-pop');
      const arrow = browser.element('coach-pop-arrow');
      return {{left: parseFloat(pop.style.left), note: !browser.element('lesson').classList.contains('hidden'),
              target: browser.element('coach-box').dataset.target,
              arrow: arrow.classList.contains('hidden'), arrowRight: arrow.style.right}};
    """)
    result = seen["result"]

    assert result["note"] is True and result["target"] == "#topology-hops"
    assert result["left"] + 340 <= 620, f"the popover overlaps the note: {result}"
    assert (result["arrow"], result["arrowRight"]) == (False, "-6px")

def test_a_terminal_popover_moves_left_of_an_open_note(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + NOTE_OPEN_AT, scenario=f"""
      await browser.click('note-pill');
      await browser.click('[data-pane="waf"]');
      {to("excluded", "f6")}
      await browser.wait(16);
      const pop = browser.element('coach-pop').style;
      return {{left: parseFloat(pop.left), top: parseFloat(pop.top), box: browser.element('coach-box').style.zIndex}};
    """)
    result = seen["result"]

    assert result["left"] + 340 <= 620 - 14, f"the popover overlaps the note: {result}"
    assert result["left"] >= 200 and result["top"] == 434
    assert int(result["box"]) < 35

def test_an_open_note_s_tab_follows_the_step(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      await browser.click('note-pill');
      await browser.click('[data-tab="hint"]');
      {to("engine")}
      return {{engine: document.querySelector('.tab[aria-selected="true"]').dataset.tab,
              open: !browser.element('lesson').classList.contains('hidden')}};
    """)

    assert seen["result"] == {"engine": "steps", "open": True}

INSECURE = """
const selected = [];
Object.getPrototypeOf(document.body).select = function () { selected.push(this.value); };
document.execCommand = (command) => command === 'copy' && selected.length > 0;
"""

def test_copy_falls_back_to_a_selection_when_the_page_is_not_a_secure_context(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + INSECURE, scenario=f"""
      {to("excluded", "f6")}
      await browser.click('coach-pop-copy');
      return {{selected, said: browser.text('coach-pop-copy'), left: document.querySelectorAll('textarea').length}};
    """)

    assert seen["result"] == {"selected": [commands("f6")["excluded"]], "said": english("lesson.copied"), "left": 0}

def test_copy_says_it_failed_when_neither_way_works(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6"), scenario=f"""
      {to("excluded", "f6")}
      await browser.click('coach-pop-copy');
      return browser.text('coach-pop-copy');
    """)

    assert seen["result"] == english("lesson.copy_failed")

WAF_TERMINAL = """
const pasted = [];
const entered = [];
pane.contentWindow = {term: {paste: (text) => pasted.push(text), input: (text) => entered.push(text), focus() {}}};
"""

def test_run_in_terminal_pastes_the_command_with_a_newline_so_it_runs(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + WAF_TERMINAL, scenario=f"""
      await browser.click('[data-pane="waf"]');
      {to("excluded", "f6")}
      await browser.click('coach-pop-run');
      return {{pasted, entered, said: browser.text('coach-pop-typed')}};
    """)
    result = seen["result"]

    assert result["pasted"] == [commands("f6")["excluded"] + "\n"], "one paste, ending in a newline"
    assert result["entered"] == ["\r"], "Enter as well, since bash keeps a bracketed paste's newline as text"
    assert result["said"] == english("lesson.ran")

def test_run_in_terminal_opens_the_waf_terminal_first_when_another_pane_is_shown(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + WAF_TERMINAL, scenario=f"""
      {to("excluded", "f6")}
      await browser.click('coach-pop-run');
      return {{pasted: pasted.length, waf: document.querySelector('[data-pane="waf"]').getAttribute('aria-selected'),
              src: browser.element('pane-frame').getAttribute('src')}};
    """)

    assert seen["result"] == {"pasted": 1, "waf": "true", "src": "/vm-terminal/fsl-waf/"}

def test_the_sent_check_polls_and_passes_once_the_platform_has_the_learner_s_own_matching_request(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      const poll = async () => { for (let i = 0; i < 5; i += 1) await browser.wait(1000); };
      await poll();
      const nothing = browser.text('coach-pop-title');
      range.sent.push("/search/?q=release");
      await poll();
      const otherSearch = browser.text('coach-pop-title');
      range.sent.push("/search/?q=서울 맛집");
      await poll();
      await browser.wait(1500);
      return {nothing, otherSearch, after: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'),
              polls: range.checked.length > 0 && range.checked.every((body) => body.poll === true),
              wrong: range.used.length,
              read: browser.requests.filter((r) => r.route.includes('/detections/') || r.route.includes('/site/requests/')).length};
    """)
    result = seen["result"]

    assert result["nothing"] == result["otherSearch"] == english("lesson.logs.label.search")
    assert result["after"] == english("lesson.logs.label.engine")
    assert result["said"] == english("lesson.logs.line.search")
    assert result["polls"] is True and result["wrong"] == 0, "a poll that finds nothing is not a wrong answer"
    assert result["read"] == 0, "the platform reads the records and judges; the page only asks"

def test_a_check_that_has_not_passed_yet_says_specifically_what_is_missing_in_its_status_line(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      const poll = async () => {{ for (let i = 0; i < 5; i += 1) await browser.wait(1000); }};
      await poll();
      const search = browser.text('coach-pop-status');
      {to("probe")}
      const fresh = browser.text('coach-pop-status');
      await poll();
      return {{search, fresh, probe: browser.text('coach-pop-status'), title: browser.text('coach-pop-title')}};
    """)
    result = seen["result"]

    assert result["search"] == english("lesson.logs.fail.search")
    assert result["fresh"] == english("lesson.status.auto")
    assert result["probe"] == english("lesson.logs.fail.probe")
    assert result["title"] == english("lesson.logs.label.probe")

def test_the_answer_check_explains_949110_and_accepts_the_rule_that_matched(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      {to("rule", "f5")}
      {SUBMIT}
      const known = await submit('949110');
      const other = await submit('1234');
      await submit(' {RIGHT["rule"]} ');
      await browser.wait(1500);
      return {{known, other, title: browser.text('coach-pop-title'), said: browser.text('coach-pop-said')}};
    """)

    assert seen["result"] == {
        "known": english("lesson.attack.wrong.rule.949110"), "other": english("lesson.check.wrong"),
        "title": english("lesson.attack.label.sqlmap"), "said": english("lesson.attack.line.rule"),
    }

def test_the_choice_check_offers_its_options_and_takes_only_the_right_one(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("engine")}
      const options = [...document.querySelectorAll('#coach-pop-act [data-act="choose"]')];
      const labels = options.map((o) => o.textContent);
      document.querySelector('#coach-pop-act [data-value="modsecurity"]').click();
      await browser.settle();
      const wrong = browser.text('coach-pop-title');
      document.querySelector('#coach-pop-act [data-value="suricata"]').click();
      await browser.settle();
      await browser.wait(1500);
      return {{labels, wrong, after: browser.text('coach-pop-title')}};
    """)

    assert seen["result"]["labels"] == [
        english("lesson.logs.option.engine.modsecurity"), english("lesson.logs.option.engine.suricata"),
    ]
    assert seen["result"]["wrong"] == english("lesson.logs.label.engine")
    assert seen["result"]["after"] == english("lesson.logs.label.probe")

def test_the_sent_check_runs_when_the_site_shows_a_matching_request(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      await browser.click('[data-pane="site"]');
      const checks = () => browser.requests.filter((r) => r.route.endsWith('/search/check/')).length;
      dispatchEvent({type: 'message', data: {fslSite: "/site/1/board.com/search/?q=release"}});
      await browser.settle();
      await browser.wait(1500);
      const other = {checks: checks(), title: browser.text('coach-pop-title')};
      range.sent.push("/search/?q=서울");
      dispatchEvent({type: 'message', data: {fslSite: "/site/1/board.com/search/?q=%EC%84%9C%EC%9A%B8"}});
      await browser.settle();
      await browser.wait(1500);
      const korean = checks();
      await browser.wait(1500);
      return {other, korean, after: browser.text('coach-pop-title')};
    """)

    assert seen["result"]["other"] == {"checks": 0, "title": english("lesson.logs.label.search")}
    assert seen["result"]["korean"] == 1
    assert seen["result"]["after"] == english("lesson.logs.label.engine")

def test_the_last_step_finishes_the_lesson_only_once_it_passes(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6"), scenario=f"""
      {to("lost", "f6")}
      {SUBMIT}
      const failed = await submit('7');
      await submit('{RIGHT["lost"]}');
      const list = [...browser.element('lesson-step-list').querySelectorAll('[data-step]')];
      return {{failed, said: browser.text('coach-pop-said'), text: browser.text('coach-pop-text'),
              allDone: list.at(-1).textContent.includes('✓') && !list.slice(0, -1).some((item) => item.textContent.includes('✓')),
              hint: browser.element('coach-pop-hint').classList.contains('hidden')}};
    """)

    assert seen["result"] == {
        "failed": english("lesson.check.wrong"), "said": english("lesson.miss.line.lost"),
        "text": english("lesson.done"), "allDone": True, "hint": True,
    }

def test_a_minute_on_a_step_offers_a_hint_without_recording_one_and_each_press_climbs(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      {to("rule", "f5")}
      const state = () => ({{help: browser.text('coach-pop-help'), button: browser.text('coach-pop-hint'),
                            doIt: !browser.element('coach-pop-do').classList.contains('hidden')}});
      const start = state();
      for (let i = 0; i < 60; i += 1) await browser.wait(1000);
      const offered = state();
      const recorded = range.used.length;
      await browser.click('coach-pop-hint');
      const one = state();
      {hints(2)}
      const three = state();
      {hints(1)}
      return {{start, offered, recorded, one, three, four: state(), used: range.used, level: range.progress.rule.hint}};
    """)
    result = seen["result"]

    assert result["start"] == {"help": "", "button": english("lesson.hint.more"), "doIt": False}
    assert result["offered"] == {"help": "", "button": english("lesson.hint.available"), "doIt": False}
    assert result["recorded"] == 0, "the timer only offers a hint; the learner has not asked for one"
    assert result["one"] == {"help": english("lesson.attack.nudge.rule"), "button": english("lesson.hint.more"), "doIt": False}
    assert english("lesson.attack.answer.rule") in result["three"]["help"] and not result["three"]["doIt"]
    assert result["four"]["doIt"] is True
    assert (result["used"], result["level"]) == ([{"step": "rule", "level": "hint"}], 4)

def test_two_wrong_answers_raise_the_hint_a_level(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f3"), scenario=f"""
      {to("meaning", "f3")}
      document.querySelector('#coach-pop-act [data-value="3xx"]').click();
      await browser.settle();
      const once = browser.text('coach-pop-help');
      document.querySelector('#coach-pop-act [data-value="5xx"]').click();
      await browser.settle();
      return {{once, twice: browser.text('coach-pop-help')}};
    """)

    assert seen["result"] == {"once": "", "twice": english("lesson.http.nudge.meaning")}

def test_do_it_for_me_performs_the_step_and_records_that_help_was_used(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f5"), scenario=f"""
      {to("rule", "f5")}
      {hints(4)}
      await browser.click('coach-pop-do');
      await browser.wait(1500);
      return {{title: browser.text('coach-pop-title'), recorded: range.used,
              marked: browser.element('lesson-step-list').querySelector('[data-step="{at("rule", "f5")}"]').textContent}};
    """)
    result = seen["result"]

    assert result["title"] == english("lesson.attack.label.sqlmap")
    assert result["recorded"] == [{"step": "rule", "level": "hint"}, {"step": "rule", "level": "do"}], (
        "help is recorded on the session through the API, once per step and kind"
    )
    assert english("lesson.helped") in result["marked"]

def test_do_it_for_me_on_the_terminal_step_has_the_platform_answer_and_types_nothing(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6") + WAF_TERMINAL, scenario=f"""
      await browser.click('[data-pane="waf"]');
      {to("excluded", "f6")}
      {hints(4)}
      await browser.click('coach-pop-do');
      return {{pasted, entered, asked: browser.requests.filter((r) => r.route.endsWith('/do/')).map((r) => r.route)}};
    """)

    assert seen["result"] == {"pasted": [], "entered": [], "asked": ["/api/sessions/1/lesson/steps/excluded/do/"]}, (
        "the agent path: the platform answers from its own records; nothing is typed into the WAF terminal"
    )

def test_do_it_for_me_on_the_terminal_step_moves_on_once_the_platform_s_check_passes(client):
    seen = open_page(client, "/blue/1/", setup=coached(unit="f6"), scenario=f"""
      {to("excluded", "f6")}
      {hints(4)}
      await browser.click('coach-pop-do');
      await browser.wait(1500);
      return {{title: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'),
              marked: browser.element('lesson-step-list').querySelector('[data-step="{at("excluded", "f6")}"]').textContent}};
    """)

    assert seen["result"]["title"] == english("lesson.miss.label.sqlmap")
    assert seen["result"]["said"] == english("lesson.miss.line.excluded")
    assert english("lesson.helped") in seen["result"]["marked"]

def test_do_it_for_me_on_the_first_step_opens_the_search_in_the_site_browser(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {hints(4)}
      await browser.click('coach-pop-do');
      return {{src: browser.element('site-frame').getAttribute('src'),
              site: document.querySelector('[data-pane="site"]').getAttribute('aria-selected')}};
    """)

    assert seen["result"] == {"src": "http://console.test:8002/site/1/board.com/" + STEPS[0]["site"][1:], "site": "true"}

def test_the_do_it_yourself_path_drops_the_ready_made_filter_and_the_run_button(client):
    stretched = """
      browser.element('lesson-stretch').checked = true;
      browser.element('lesson-stretch').dispatchEvent({type: 'change'});
    """
    filtered = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {stretched}
      {to("find")}
      return document.querySelector('#coach-pop-act [data-act="chip"]') === null;
    """)
    typed = open_page(client, "/blue/1/", setup=coached(unit="f6"), scenario=f"""
      {stretched}
      {to("excluded", "f6")}
      return {{run: browser.element('coach-pop-run').classList.contains('hidden'),
              code: !browser.element('coach-pop-code-box').classList.contains('hidden'),
              said: browser.text('coach-pop-typed'), kept: localStorage.getItem('fsl-lesson-stretch')}};
    """)

    assert filtered["result"] is True
    assert typed["result"] == {"run": True, "code": True, "said": english("lesson.stretch.type"), "kept": "true"}

EVERYWHERE = """
document.querySelectorAll('.pane-tab').forEach((tab, index) => {
  tab.getBoundingClientRect = () => ({left: 8, top: 60 + 50 * index, right: 52, bottom: 104 + 50 * index, width: 44, height: 44});
});
browser.element('site-address').getBoundingClientRect = () => ({left: 300, top: 60, right: 1300, bottom: 88, width: 1000, height: 28});
['[data-test-subj="docTableExpandToggleColumn"]', '[data-test-subj="field-status"]',
 '[data-test-subj="field-source_ip"]'].forEach((selector) => present.add(selector));
"""

def test_every_step_draws_its_box_on_something_the_console_can_reach_in_both_modes(client):
    seen = open_page(client, "/blue/1/", setup=coached() + EVERYWHERE, scenario=f"""
      const visited = [];
      for (const stretch of [false, true]) {{
        browser.element('lesson-stretch').checked = stretch;
        browser.element('lesson-stretch').dispatchEvent({{type: 'change'}});
        for (let index = 0; index < {len(STEPS)}; index += 1) {{
          await browser.click('[data-pane="site"]');
          await browser.click(`[data-step="${{index}}"]`);
          await browser.wait(16);
          const box = browser.element('coach-box');
          const first = {{drawn: !box.classList.contains('hidden'), target: box.dataset.target}};
          const opens = {{0: 'site', 1: 'elk', 2: 'site', 3: 'elk', 4: 'elk', 5: 'elk'}}[index];
          if (opens) await browser.click(`[data-pane="${{opens}}"]`);
          await browser.wait(16);
          visited.push({{stretch, index, first, then: {{drawn: !box.classList.contains('hidden'), target: box.dataset.target}}}});
        }}
      }}
      return visited;
    """)
    expected = {
        "search": "#site-address", "engine": "pane", "probe": "#site-address",
        "find": '[data-test-subj="docTableExpandToggleColumn"]', "verdict": '[data-test-subj="field-status"]',
        "address": '[data-test-subj="field-source_ip"]',
    }

    assert seen["errors"] == []
    for visit in seen["result"]:
        step = IDS[visit["index"]]
        assert visit["then"] == {"drawn": True, "target": expected[step]}, (step, visit)
        assert visit["first"]["drawn"] is True, (step, visit)
        assert "site-frame" not in visit["then"]["target"], "the site page is another origin; nothing inside it is reachable"

def test_the_first_step_says_open_the_website_then_points_at_the_address_bar_with_the_full_url(client):
    seen = open_page(client, "/blue/1/", setup=coached() + EVERYWHERE, scenario="""
      await browser.wait(16);
      const closed = {text: browser.text('coach-pop-text'), target: browser.element('coach-box').dataset.target};
      await browser.click('[data-pane="site"]');
      await browser.wait(16);
      return {closed, open: {text: browser.text('coach-pop-text'), target: browser.element('coach-box').dataset.target},
              listed: browser.element('lesson-step-list').textContent};
    """)

    assert seen["result"]["closed"] == {"text": english("lesson.open.site"), "target": '.pane-tab[data-pane="site"]'}
    assert seen["result"]["open"] == {"text": english("lesson.logs.coach.search"), "target": "#site-address"}
    assert "http://board.com/search/?q=" in english("lesson.logs.coach.search")

def test_a_popover_for_the_wide_address_bar_sits_just_below_its_right_end(client):
    seen = open_page(client, "/blue/1/", setup=coached() + EVERYWHERE, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.wait(16);
      const pop = browser.element('coach-pop').style;
      return {left: parseFloat(pop.left), top: parseFloat(pop.top), arrow: browser.element('coach-pop-arrow').style.top};
    """)

    assert seen["result"] == {"left": 1300 - 340, "top": 88 + 14, "arrow": "-6px"}, (
        "below the bar and right-aligned, not in the middle of the page"
    )

DEV = """
const records = {
  1: {id: 1, at: 1, method: "GET", url: "http://board.com/", status: 200, blocked: false, ms: 12,
      request_headers: {Host: "board.com", "X-FSL-Case": "browse"}, response_headers: {"Content-Type": "text/html"},
      request_body: null, response_body: {text: "<html>home</html>", size: 17, truncated: false}},
  2: {id: 2, at: 2, method: "GET", url: "http://board.com/search/?q=O%27Brien", status: 403, blocked: true, ms: 9,
      request_headers: {Host: "board.com"}, response_headers: {Server: "nginx"},
      request_body: null, response_body: {text: "x".repeat(2500), size: 70000, truncated: true}},
};
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: false, lesson: null, site: {port: 8002, path: "/site/1/board.com/"}}};
  }
  if (request.route === "/api/sessions/1/site/requests/") {
    return {body: Object.values(records).filter((r) => r.id > Number(request.query.after || 0))
      .map(({id, at, method, url, status, blocked, ms}) => ({id, at, method, url, status, blocked, ms}))};
  }
  const one = /^\\/api\\/sessions\\/1\\/site\\/requests\\/(\\d+)\\/$/.exec(request.route);
  if (one) return {body: records[one[1]]};
  return {status: 404, body: {}};
});
"""

def test_the_address_bar_shows_the_full_url_and_says_an_http_site_is_not_secure(client):
    seen = open_page(client, "/blue/1/", setup=DEV, scenario="""
      await browser.click('[data-pane="site"]');
      return {address: browser.element('site-address').value, marker: browser.text('site-insecure').trim()};
    """)

    assert seen["result"] == {"address": "http://board.com/", "marker": english("site.not_secure")}

def test_developer_tools_list_the_pane_s_requests_with_blocked_ones_in_red(client):
    seen = open_page(client, "/blue/1/", setup=DEV, scenario="""
      await browser.click('[data-pane="site"]');
      const closed = browser.element('site-dev').classList.contains('hidden');
      await browser.click('site-dev-toggle');
      const rows = [...browser.element('site-dev-rows').querySelectorAll('[data-request]')];
      await browser.wait(2000);
      return {closed, open: !browser.element('site-dev').classList.contains('hidden'),
              rows: rows.map((row) => row.textContent.replace(/\\s+/g, ' ').trim()),
              red: rows[1].querySelector('.text-danger').textContent,
              polled: browser.requests.filter((r) => r.route === '/api/sessions/1/site/requests/').map((r) => r.query.after),
              frameBottom: browser.element('site-frame').style.bottom,
              cookies: browser.element('site-dev').textContent.includes(STRINGS.en['site.dev.cookies'])};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert (result["closed"], result["open"]) == (True, True)
    assert result["rows"][0].startswith("GET http://board.com/ 200")
    assert "http://board.com/search/?q=O%27Brien 403" in result["rows"][1]
    assert english("site.dev.blocked") in result["red"]
    assert result["polled"] == ["0", "2"], "the panel asks only for what is new"
    assert result["frameBottom"] == "280px", "the panel is docked under the page, not over it"
    assert result["cookies"] is True

def test_a_selected_request_shows_its_headers_and_bodies_and_more_shows_the_rest(client):
    seen = open_page(client, "/blue/1/", setup=DEV, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      await browser.click('[data-request="2"]');
      const detail = () => browser.element('site-dev-detail');
      const before = detail().querySelector('[data-body="response"]').textContent.length;
      const text = detail().textContent;
      await browser.click('[data-more="response"]');
      return {before, after: detail().querySelector('[data-body="response"]').textContent.length, text};
    """)
    result = seen["result"]

    assert english("site.dev.request_headers") in result["text"] and "Host: board.com" in result["text"]
    assert english("site.dev.response_headers") in result["text"] and "Server: nginx" in result["text"]
    assert english("site.dev.truncated", 70000) in result["text"]
    assert (result["before"], result["after"]) == (2000, 2500)

def test_view_source_shows_what_the_waf_returned_for_the_current_page(client):
    seen = open_page(client, "/blue/1/", setup=DEV, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      await browser.click('site-dev-source');
      return browser.element('site-dev-detail').textContent;
    """)

    assert "<html>home</html>" in seen["result"]
    assert english("site.dev.source_of", "http://board.com/") in seen["result"]

def test_the_developer_tools_can_be_dragged_taller(client):
    seen = open_page(client, "/blue/1/", setup=DEV + """
      browser.element('site-frame').parentNode.getBoundingClientRect =
        () => ({left: 60, top: 100, right: 1440, bottom: 900, width: 1380, height: 800});
    """, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      browser.element('site-dev-grip').dispatchEvent({type: 'mousedown', preventDefault() {}});
      dispatchEvent({type: 'mousemove', clientY: 500});
      dispatchEvent({type: 'mouseup'});
      dispatchEvent({type: 'mousemove', clientY: 300});
      return [browser.element('site-dev').style.height, browser.element('site-frame').style.bottom];
    """)

    assert seen["result"] == ["400px", "400px"]


def test_help_recorded_on_the_session_is_marked_when_the_page_is_opened_again(client):
    seen = open_page(client, "/blue/1/", setup=coached() + "range.used.push({step: 'find', level: 'do'});", scenario=f"""
      return browser.element('lesson-step-list').querySelector('[data-step="{at("find")}"]').textContent;
    """)

    assert english("lesson.helped") in seen["result"], "the mark comes from the session, not from this browser"

def test_the_note_and_its_pill_start_below_the_site_toolbar_and_the_waf_banner(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      const tops = () => [browser.element('note-pill').style.top, browser.element('lesson').style.top];
      const onKibana = tops();
      await browser.click('[data-pane="site"]');
      const onSite = tops();
      await browser.click('[data-pane="waf"]');
      return {onKibana, onSite, onWaf: tops()};
    """)

    assert seen["result"] == {"onKibana": ["8px", "8px"], "onSite": ["48px", "48px"], "onWaf": ["48px", "48px"]}, (
        "the address bar, the developer tools button and the WAF banner stay uncovered"
    )

def test_a_closed_session_s_lesson_and_network_panel_stop_polling(client):
    seen = open_page(client, "/blue/1/", setup=coached() + "range.ended_at = '2026-10-11T00:00:00Z';", scenario=f"""
      {to("search")}
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      const before = browser.requests.length;
      for (let second = 0; second < 12; second += 1) await browser.wait(1000);
      return browser.requests.slice(before).map((r) => r.route);
    """)

    polled = [route for route in seen["result"] if route.endswith(("/ingest/", "/detections/", "/waf/", "/check/", "/site/requests/"))]
    assert polled == [], "nothing keeps asking the platform about a session that has closed"

def test_an_open_session_s_lesson_and_network_panel_keep_polling(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("search")}
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      const before = browser.requests.length;
      for (let second = 0; second < 12; second += 1) await browser.wait(1000);
      return browser.requests.slice(before).map((r) => r.route);
    """)

    assert "/api/sessions/1/lesson/steps/search/check/" in seen["result"] and "/api/sessions/1/site/requests/" in seen["result"]

def test_the_home_card_shows_each_foundation_s_title_what_it_teaches_and_its_time_and_starts_it_or_the_wargame(client):
    posted = []
    for button in ('[data-lesson-id="f1"]', '[data-wargame-start="board"] button'):
        seen = open_page(client, "/", setup=CATALOGUE, scenario=f"""
          const card = browser.text('[data-foundation="f1"]');
          await browser.click('{button}');
          return {{card, posted: browser.requests.filter((r) => r.method === 'POST').map((r) => r.body)}};
        """)
        assert seen["errors"] == []
        posted += seen["result"]["posted"]
    card = seen["result"]["card"]

    for shown in (english("lesson.range.title"), english("lesson.range.learns"), english("main.minutes", 10),
                  english("main.foundation.start")):
        assert shown in card, shown
    assert posted == [
        {"scenario": "board", "guidance": True, "lesson": "f1", "defense": "minimal"},
        {"scenario": "board"},
    ], "a foundation runs guided on the defense it declares; the wargame runs without guidance on the full defense"

def test_the_first_open_of_a_foundation_lands_on_the_theory_tab_and_a_later_one_starts_folded(client):
    first = open_page(client, "/blue/1/", setup=guided(True) + "localStorage.removeItem('fsl-lesson-landed-1');", scenario="""
      const shown = [...document.querySelectorAll('[data-pane-of]')]
        .filter((pane) => !pane.classList.contains('hidden')).map((pane) => pane.dataset.paneOf);
      return {open: !browser.element('lesson').classList.contains('hidden'), shown,
              landed: localStorage.getItem('fsl-lesson-landed-1')};
    """)
    later = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      return browser.element('lesson').classList.contains('hidden');
    """)

    assert first["errors"] == []
    assert first["result"] == {"open": True, "shown": ["theory"], "landed": "true"}
    assert later["result"] is True

def test_why_on_a_step_opens_the_theory_card_that_explains_it(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      const first = browser.element('coach-pop-why').classList.contains('hidden');
      {to("engine")}
      const shown = !browser.element('coach-pop-why').classList.contains('hidden');
      await browser.click('coach-pop-why');
      const card = document.querySelector('#lesson-theory [data-card="records"]');
      return {{first, shown, tab: JSON.parse(localStorage.getItem('fsl-lesson-note')).tab,
              open: !browser.element('lesson').classList.contains('hidden'),
              expanded: card.getAttribute('aria-expanded')}};
    """)

    assert seen["result"] == {"first": True, "shown": True, "tab": "theory", "open": True, "expanded": "true"}

MINE = CATALOGUE.replace('  if (request.route === "/api/sessions/" && request.method === "POST")', """  if (request.route === "/api/sessions/" && request.query.ids) {
    seen.ids = request.query.ids;
    return {body: [
      {id: 12, scenario: "board", kind: "lesson", lesson_id: "f1", ended_at: "2026-10-13T10:00:00Z",
       result: {objectives: {lost: 0, undetected: 0, total: 3}, scenario: null}},
      {id: 9, scenario: "board", kind: "lesson", lesson_id: "f1", ended_at: "2026-10-12T10:00:00Z",
       result: {objectives: {lost: 0, undetected: 0, total: 3}, scenario: null}},
    ]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST")""")

def test_the_home_page_shows_each_foundation_s_last_session_from_the_sessions_this_browser_opened(client):
    seen = open_page(client, "/", setup="const seen = {};\nlocalStorage.setItem('fsl-opened-sessions', '[12, 9]');\n" + MINE,
                     scenario="""
      await browser.settle();
      const line = document.querySelector('[data-last="board/f1"]');
      return {ids: seen.ids, hidden: line.classList.contains('hidden'), text: line.textContent,
              href: line.querySelector('a').getAttribute('href')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["ids"] == "12,9"
    assert seen["result"]["hidden"] is False and seen["result"]["href"] == "/session/12/"
    assert english("main.last", 12, english("kind.lesson")) in seen["result"]["text"]
    assert english("state.closed") in seen["result"]["text"]

def test_a_browser_with_no_remembered_session_asks_for_none_and_storage_that_throws_breaks_nothing(client):
    seen = open_page(client, "/", setup="const seen = {};\n" + MINE + """
      Object.defineProperty(globalThis, 'localStorage', {value: {getItem() { throw new Error('blocked'); },
                                                                setItem() { throw new Error('blocked'); }}});
    """, scenario="""
      await browser.settle();
      return {ids: seen.ids || null, hidden: document.querySelector('[data-last="board/f1"]').classList.contains('hidden')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"ids": None, "hidden": True}
