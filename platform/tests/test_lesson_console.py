import json
import re

import pytest

import wargames
from api import views
from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

STEPS = wargames.lesson("board")["steps"]
SHOWN = [views._shown_step(None, dict(step, query=None)) | {k: v for k, v in step.items() if k == "query"} for step in STEPS]
IDS = [step["id"] for step in STEPS]
COMMAND = {step["id"]: step.get("command", "") for step in STEPS}

GUIDED = """
const range = {detections: [], waf: {paranoia: 4, exclusions: [], version: "v1"}, status: 403, passed: false, puts: [], used: [],
               ended_at: null, progress: {}, fired: [], checked: [], states: []};
const FULL = FULL_JSON;
const own = (id) => (range.progress[id] = range.progress[id] || {hint: 0, done_for_me: false, wrong: 0, after: 0, tried: null, passed: null, skipped: null});
const used = (entry) => { if (!range.used.some((one) => one.step === entry.step && one.level === entry.level)) range.used.push(entry); };
const stepState = (id, extra) => ({...extra, hint: own(id).hint, hints: range.used, progress: range.progress});
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
  const fail = `lesson.board.fail.${id}`;
  if (check.kind === "click") return passing(id);
  if (check.kind === "answer" || check.kind === "choice") {
    const given = String(body.answer || "").trim();
    if (check.accept.includes(given)) return passing(id);
    return failing(id, false, (check.known || []).includes(given) ? `lesson.board.wrong.${id}.${given}` : "lesson.check.wrong");
  }
  if (check.kind === "alert") {
    range.checked.push(body);
    const found = range.detections.some((row) => row.id > own(id).after && row.marker === check.marker
      && decodeURIComponent(row.path).includes(check.path));
    return found ? passing(id) : failing(id, body.poll, fail);
  }
  if (check.kind === "waf") {
    const there = range.waf.exclusions.some((entry) => entry.rule_id === check.rule_id && entry.target === check.target
      && entry.path === check.path);
    if (!there) return failing(id, body.poll, fail);
    if (body.poll && own(id).tried === range.waf.version) return failing(id, true, `${fail}.reload`);
    own(id).tried = range.waf.version;
    range.fired.push(check.case);
    return range.status === 200 ? passing(id) : failing(id, body.poll, `${fail}.reload`);
  }
  if (check.kind === "served") {
    range.fired.push(check.case);
    return range.status === 200 ? passing(id) : failing(id, body.poll, fail, [range.status]);
  }
  return range.passed ? passing(id) : failing(id, body.poll, "lesson.board.fail.verify");
};
browser.serve((request) => {
  const parts = request.route.split("/");
  const stepped = parts[4] === "lesson" && parts[5] === "steps" ? [request.route, parts[6], parts[7] ? `${parts[7]}/` : ""] : null;
  if (stepped && !stepped[2]) {
    const id = stepped[1];
    range.states.push([id, request.body.state]);
    if (request.body.state === "reached") own(id).after = Math.max(0, ...range.detections.map((row) => row.id));
    else if (!own(id).passed) own(id).skipped = "now";
    return {body: stepState(id, {})};
  }
  if (stepped && stepped[2] === "check/") return {body: judge(stepped[1], request.body)};
  if (stepped) {
    const id = stepped[1];
    own(id).done_for_me = true;
    used({step: id, level: "do"});
    const check = FULL[id];
    if (check.kind === "answer" || check.kind === "choice") return {body: judge(id, {answer: check.accept[0]})};
    if (check.kind === "waf") {
      const tuning = {paranoia: range.waf.paranoia, exclusions: [...range.waf.exclusions,
        {rule_id: check.rule_id, target: check.target, path: check.path}]};
      range.puts.push(tuning);
      range.waf = {...tuning, version: "v-do"};
      return {body: judge(id, {})};
    }
    if (check.kind === "click" || check.kind === "served") return {body: judge(id, {})};
    return {body: stepState(id, {passed: false, reason: null})};
  }
  if (request.route === "/api/sessions/1/" && request.method === "PATCH") {
    range.patched = request.body;
    return {body: {id: 1, mode: request.body.mode}};
  }
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: GUIDANCE, mode: range.mode || "guided", hints: range.used, progress: range.progress, ended_at: range.ended_at, waf_box: "fsl-1-waf", discover: "/kibana/app/discover#/",
                   site: {port: 8002, path: "/site/1/board.com/"},
                   waf_rules: "/etc/modsecurity.d/owasp-crs/rules", lesson: GUIDANCE ? {
      text: "lesson.board",
      cases: ["board-sqli-orderby-sqlmap", "board-normal-search-with-apostrophe"],
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
  if (request.route === "/api/sessions/1/detections/") {
    return {body: range.detections.filter((row) => row.id > Number(request.query.after || 0))};
  }
  if (request.route === "/api/sessions/1/waf/" && request.method === "GET") return {body: range.waf};
  if (request.route === "/api/sessions/1/waf/" && request.method === "PUT") {
    range.puts.push(request.body);
    range.waf = {...request.body, version: "v2"};
    return {body: range.waf};
  }
  if (request.route === "/api/sessions/1/attacks/") return {status: 201, body: {meta: {status: range.status}, diagnosis: range.diagnosis}};
  if (request.route === "/api/sessions/1/verify/") {
    return {body: {passed: range.passed, run: "r", cases: [
      {name: "board-sqli-orderby-sqlmap", malicious: true, outcome: "held"},
      {name: "board-normal-search-with-apostrophe", malicious: false, outcome: range.passed ? "served" : "blocked"},
    ], diagnosis: range.passed ? [["lesson.diag.blocked_ratio", [1, 1]]] : [
      ["lesson.diag.blocked_ratio", [1, 1]],
      ["lesson.diag.benign_blocked", ["board-normal-search-with-apostrophe", 403]],
    ]}};
  }
  return {status: 404, body: {detail: "not served"}};
});
""".replace("THEORY_JSON", json.dumps(wargames.lesson("board")["theory"])).replace(
    "HINTS_JSON", json.dumps(wargames.lesson("board")["hints"])).replace("STEPS_JSON", json.dumps([
    dict(step, discover="/kibana/app/discover#/?narrowed=brien") if step.get("query") else step for step in SHOWN
])).replace("FULL_JSON", json.dumps({step["id"]: step["check"] for step in STEPS}))

def guided(guidance):
    return GUIDED.replace("GUIDANCE", "true" if guidance else "false")

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
    assert english("lesson.board.read") in shown["result"]["paragraphs"]
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

def test_the_note_has_steps_goal_theory_hints_and_check_tabs_and_shows_one_at_a_time(client):
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

    assert seen["result"]["tabs"] == ["steps", "goal", "theory", "hint", "check"]
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
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      const hidden = () => browser.element('lesson-answer-box').classList.contains('hidden');
      const cards = [...browser.element('lesson-hints').querySelectorAll('[data-card]')].map((c) => c.dataset.card);
      const folded = hidden();
      await browser.click('lesson-answer-toggle');
      return {cards, folded, opened: !hidden(), answer: browser.text('lesson-answer'),
              hints: browser.text('lesson-hints'),
              form: ['lesson-paranoia', 'lesson-exclusions', 'lesson-save'].map((id) => document.getElementById(id)),
              writes: browser.requests.filter((r) => r.method !== 'GET' && !r.route.startsWith('/api/sessions/1/lesson/steps/')).map((r) => r.route)};
    """)

    assert seen["result"]["cards"] == ["why_rule", "why_target", "why_file"]
    assert english("lesson.board.hint.why_rule.title") in seen["result"]["hints"]
    assert "nginx" not in seen["result"]["hints"], "a hint says why, the steps say what to type"
    assert seen["result"]["folded"] is True and seen["result"]["opened"] is True
    assert "ctl:ruleRemoveTargetById=920273;ARGS:q" in seen["result"]["answer"]
    assert "if nginx -t 2>&1 && nginx -s reload 2>&1; then echo reloaded;" in seen["result"]["answer"]
    assert seen["result"]["form"] == [None, None, None], "the tuning is done in the WAF terminal"
    assert seen["result"]["writes"] == []

def test_verify_shows_pass_or_fail_with_passing_lines_in_green_and_failing_lines_in_red(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('lesson-verify');
      const passed = browser.element('lesson-passed');
      const failing = browser.element('lesson-diagnosis');
      return {verdict: browser.text('lesson-verdict'), passed: passed.textContent, failing: failing.textContent,
              green: passed.querySelectorAll('.text-success').length,
              red: failing.querySelectorAll('.text-danger').length,
              asked: browser.requests.filter((r) => r.method === 'POST' && !r.route.startsWith('/api/sessions/1/lesson/steps/')).map((r) => r.route)};
    """)
    result = seen["result"]

    assert result["asked"] == ["/api/sessions/1/verify/"]
    assert "FAIL" in result["verdict"] and english("lesson.verify.failing", 1) in result["verdict"]
    assert "✓" in result["passed"] and english("lesson.check.held") in result["passed"]
    assert result["green"] == 1 and result["red"] == 1
    assert english("lesson.diag.benign_blocked", "board-normal-search-with-apostrophe", 403) in result["failing"]
    assert "✗" in result["failing"] and english("lesson.diag.blocked_ratio", 1, 1) not in result["failing"]
    assert not re.search(r"\b(TP|FP|FN|TN)\b", result["passed"] + result["failing"]), (
        "the learner is told what happened, not the scoreboard's labels"
    )

def test_replay_fires_the_chosen_lesson_case_through_the_attacks_api(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.force('lesson-case', 'board-normal-search-with-apostrophe');
      await browser.click('lesson-replay');
      return browser.requests.filter((r) => r.method === 'POST' && !r.route.startsWith('/api/sessions/1/lesson/steps/')).map((r) => [r.route, r.body]);
    """)

    assert seen["result"] == [[
        "/api/sessions/1/attacks/", {"case": "board-normal-search-with-apostrophe", "lesson": True},
    ]], "marked as the lesson's own replay, so neither score counts it"

def test_a_lesson_replay_that_leaked_says_so_beside_the_run(client):
    seen = open_page(client, "/blue/1/", setup=guided(True) + """
      range.diagnosis = [["lesson.diag.leaked", ["board-sqli-orderby-sqlmap", 3, 3]]];
    """, scenario="""
      await browser.force('lesson-case', 'board-sqli-orderby-sqlmap');
      await browser.click('lesson-replay');
      return browser.text('lesson-replay-status');
    """)

    assert english("lesson.diag.leaked", "board-sqli-orderby-sqlmap", 3, 3) in seen["result"]

CATALOGUE_DECLARING = """
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [
      {id: "board", name: "Board", description: "", cases: 1, lesson: true, lesson_defense: DECLARED,
       lessons: [{id: "waf-exclusion", order: 1, title: "lesson.board.title", goal: "lesson.board.summary",
                  minutes: 40, level: "easy", defense: DECLARED, prerequisites: [], steps: 8}]},
      {id: "corp", name: "Corp", description: "", cases: 1, lesson: false},
    ]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 9}};
  return {status: 404, body: {detail: "not served"}};
});
"""

CATALOGUE = CATALOGUE_DECLARING.replace("DECLARED", '"minimal"')

def test_only_a_scenario_with_a_lesson_offers_to_start_as_one_and_it_opens_a_guided_minimal_session(client):
    seen = open_page(client, "/", setup=CATALOGUE, scenario="""
      const lessons = [...document.querySelectorAll('[data-lesson]')].map((b) => b.dataset.wargame);
      await browser.click('[data-lesson="true"]');
      return {lessons, posted: browser.requests.filter((r) => r.method === 'POST' && r.route !== '/api/sessions/1/ingest/').map((r) => r.body)};
    """)

    assert seen["errors"] == []
    assert seen["result"]["lessons"] == ["board", "board"], "the lesson and practice rungs of the one lesson"
    assert seen["result"]["posted"] == [{"scenario": "board", "guidance": True, "lesson": "waf-exclusion", "defense": "minimal"}]

def test_start_as_lesson_sends_the_defense_the_lesson_declares_not_a_fixed_one(client):
    seen = open_page(client, "/", setup=CATALOGUE_DECLARING.replace("DECLARED", '"full"'), scenario="""
      await browser.click('[data-lesson="true"]');
      return browser.requests.filter((r) => r.method === 'POST').map((r) => r.body);
    """)

    assert seen["result"] == [{"scenario": "board", "guidance": True, "lesson": "waf-exclusion", "defense": "full"}]

def test_the_goal_line_is_pinned_above_the_tabs_whichever_tab_is_open(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('note-pill');
      await browser.click('[data-tab="theory"]');
      return {text: browser.text('lesson-goal-line'), hidden: browser.element('lesson-goal-line').classList.contains('hidden')};
    """)
    page = client.get("/blue/1/").content.decode()

    assert seen["result"] == {"text": english("lesson.board.summary"), "hidden": False}
    assert page.index('id="lesson-goal-line"') < page.index('id="lesson-tabs"') < page.index('data-pane-of="steps"'), (
        "the goal sits above the tabs, outside every tab's pane"
    )
    assert "is not injectable" in english("lesson.board.summary") and "O'Brien" in english("lesson.board.summary")

def test_the_catalogue_says_which_scenario_carries_a_lesson(client):
    listed = {w["id"]: w["lesson"] for w in client.get("/api/wargames/").json()}

    assert listed == {"board": True, "corp": False}

EXPAND = '[data-test-subj="docTableExpandToggleColumn"]'

COACHED = GUIDED.replace("GUIDANCE", "GUIDED_FLAG") + """
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
browser.element('lesson-verify').getBoundingClientRect =
  () => ({left: 1100, top: 300, right: 1180, bottom: 330, width: 80, height: 30});
"""

def coached(guidance=True):
    return COACHED.replace("GUIDED_FLAG", "true" if guidance else "false")

def at(step):
    return IDS.index(step)

def to(step):
    return f"await browser.click('[data-step=\"{at(step)}\"]');"

def hints(times):
    return "for (let i = 0; i < %d; i += 1) await browser.click('coach-pop-hint');" % times

def test_the_lesson_is_seven_steps_each_checked_by_the_platform():
    assert IDS == ["search", "find", "rule", "target", "exclude", "retry", "verify"]
    assert [step["check"]["kind"] for step in STEPS] == [
        "alert", "click", "answer", "choice", "waf", "served", "verify",
    ]

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
    assert english("lesson.board.nudge.find") in seen["result"]["help"]
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
        "hidden": False, "count": f"1 / {len(STEPS)}", "title": english("lesson.board.label.search"),
        "text": english("lesson.open.site"), "command": True, "status": english("lesson.board.fail.search"),
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

def test_the_coach_walks_on_to_the_lesson_note_s_own_controls_and_opens_the_check_tab(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("verify")}
      await browser.wait(16);
      const box = browser.element('coach-box');
      return {{text: browser.text('coach-pop-text'), left: box.style.left, layer: box.style.zIndex,
              note: browser.element('lesson').classList.contains('hidden'),
              check: document.querySelector('[data-pane-of="check"]').classList.contains('hidden')}};
    """)

    assert seen["result"] == {
        "text": english("lesson.board.coach.verify"), "left": "1096px", "layer": "9999", "note": False, "check": False,
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
    assert seen["result"]["missed"] == english("lesson.board.label.find"), "a click elsewhere does not advance"
    assert seen["result"]["after"] == english("lesson.board.label.rule")
    assert seen["result"]["said"] == english("lesson.board.line.find"), "the step's line greets the next step"
    assert seen["result"]["status"] == "✓ " + english("lesson.board.ok.find"), "the pass is said before moving on"

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

    assert seen["result"] == {"label": english("lesson.board.chip.find"),
                              "src": "/kibana/app/discover#/?narrowed=brien", "kibana": "true"}

def test_the_steps_tab_lists_the_steps_with_the_current_one_marked_and_leaves_the_words_to_the_popover(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      await browser.click('note-pill');
      await browser.click('coach-pop-next');
      const listed = [...browser.element('lesson-step-list').querySelectorAll('[data-step]')];
      const steps = document.querySelector('[data-pane-of="steps"]');
      return {listed: listed.length, done: listed[0].textContent.includes('✓'),
              current: listed[1].textContent, buttons: steps.querySelectorAll('button:not([data-step])').length,
              repeated: steps.textContent.includes(browser.text('coach-pop-text')),
              shown: browser.element('lesson-coach-show').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert (result["listed"], result["done"]) == (len(STEPS), True)
    assert english("lesson.board.label.find") in result["current"]
    assert english("lesson.status.current") in result["current"]
    assert result["repeated"] is False, "the instruction is said once, in the popover"
    assert (result["buttons"], result["shown"]) == (1, True), "no Back or Next of its own; Show the guide only once closed"

def test_a_step_in_the_list_jumps_the_guide_there(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("exclude")}
      return browser.text('coach-pop-title');
    """)

    assert seen["result"] == english("lesson.board.label.exclude")

def test_the_step_reached_is_kept_per_session_and_resumed_on_the_next_visit(client):
    seen = open_page(client, "/blue/1/", setup=coached() + f"""
      localStorage.setItem('fsl-lesson-step-1', '{at("exclude") + 1}');
    """, scenario="""
      const resumed = browser.text('coach-pop-title');
      await browser.click('coach-pop-next');
      return {resumed, kept: localStorage.getItem('fsl-lesson-step-1')};
    """)

    assert seen["result"] == {"resumed": english("lesson.board.label.exclude"), "kept": str(at("exclude") + 2)}

def test_next_and_a_jump_in_the_list_record_a_step_left_unpassed_as_skipped_and_back_does_not(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      await browser.click('coach-pop-next');
      {to("rule")}
      document.querySelector('#coach-pop-act [data-act="value"]').value = '920273';
      document.querySelector('#coach-pop-act [data-act="answer"]').dispatchEvent({{type: 'submit', preventDefault() {{}}}});
      await browser.settle();
      await browser.wait(1500);
      await browser.click('coach-pop-next');
      await browser.click('coach-pop-back');
      await browser.settle();
      return range.states;
    """)

    assert seen["result"] == [
        ["search", "reached"], ["search", "skipped"], ["find", "reached"], ["find", "skipped"], ["rule", "reached"],
        ["target", "reached"], ["target", "skipped"], ["exclude", "reached"], ["target", "reached"],
    ], "a passed step moves on without a skip; Back is not a skip"

def test_the_hint_level_a_step_reached_is_resumed_from_the_session(client):
    seen = open_page(client, "/blue/1/", setup=coached() + "own('rule').hint = 1;", scenario=f"""
      {to("rule")}
      return browser.text('coach-pop-help');
    """)

    assert seen["result"] == english("lesson.board.nudge.rule"), "the level comes from the session, not from this browser"

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

def test_a_guided_note_teaches_with_folded_theory_cards_that_open_on_a_click(client):
    shown = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      const cards = [...browser.element('lesson-theory').querySelectorAll('[data-card]')];
      const folded = cards.map((card) => browser.element('lesson-theory')
        .querySelector(`[data-card-body="${card.dataset.card}"]`).classList.contains('hidden'));
      await browser.click('[data-card="scoring"]');
      const body = browser.element('lesson-theory').querySelector('[data-card-body="scoring"]');
      return {ids: cards.map((card) => card.dataset.card), folded, opened: !body.classList.contains('hidden'),
              text: body.textContent};
    """)

    assert shown["errors"] == []
    assert shown["result"]["ids"] == ["paranoia", "scoring", "culprit", "fixes", "anatomy"]
    assert all(shown["result"]["folded"]), "theory stays out of the path until it is asked for"
    assert shown["result"]["opened"] is True
    assert english("lesson.board.theory.scoring.body") in shown["result"]["text"]

def test_a_theory_card_points_the_coach_at_what_it_talks_about(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario="""
      await browser.click('[data-card="anatomy"]');
      await browser.click('[data-shows="exclude"]');
      const anatomy = browser.text('coach-pop-title');
      await browser.click('[data-card="culprit"]');
      await browser.click('[data-shows="rule"]');
      return {anatomy, culprit: browser.text('coach-pop-title')};
    """)

    assert seen["result"] == {
        "anatomy": english("lesson.board.label.exclude"), "culprit": english("lesson.board.label.rule"),
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
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      await browser.click('[data-pane="waf"]');
      {to("exclude")}
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
        "does": english("lesson.board.does.exclude"), "wide": True, "popLeft": "644px", "popTop": "434px",
    }, "the popover sits in the pane's bottom right corner, clear of the terminal output"
    assert result["code"] == COMMAND["exclude"] and result["shown"] is True
    assert result["view"] == english("lesson.command.hide")

def test_the_copy_button_puts_the_step_s_command_on_the_clipboard(client):
    seen = open_page(client, "/blue/1/", setup=coached() + """
      const copied = [];
      navigator.clipboard = {writeText: async (text) => { copied.push(text); }};
    """, scenario=f"""
      {to("exclude")}
      await browser.click('coach-pop-view');
      await browser.click('coach-pop-copy');
      return {{copied, said: browser.text('coach-pop-copy')}};
    """)

    assert seen["result"] == {"copied": [COMMAND["exclude"]], "said": english("lesson.copied")}

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

def test_a_popover_for_a_note_control_sits_beside_the_note_not_over_it(client):
    seen = open_page(client, "/blue/1/", setup=coached() + NOTE_OPEN_AT + """
      browser.element('lesson-verify').getBoundingClientRect =
        () => ({left: 640, top: 300, right: 720, bottom: 330, width: 80, height: 30});
    """, scenario=f"""
      {to("verify")}
      await browser.wait(16);
      const pop = browser.element('coach-pop');
      const arrow = browser.element('coach-pop-arrow');
      return {{left: parseFloat(pop.style.left), note: !browser.element('lesson').classList.contains('hidden'),
              arrow: arrow.classList.contains('hidden'), arrowRight: arrow.style.right}};
    """)
    result = seen["result"]

    assert result["note"] is True
    assert result["left"] + 340 <= 620, f"the popover overlaps the note: {result}"
    assert (result["arrow"], result["arrowRight"]) == (False, "-6px")

def test_a_terminal_popover_moves_left_of_an_open_note(client):
    seen = open_page(client, "/blue/1/", setup=coached() + NOTE_OPEN_AT, scenario=f"""
      await browser.click('note-pill');
      await browser.click('[data-pane="waf"]');
      {to("exclude")}
      await browser.wait(16);
      const pop = browser.element('coach-pop').style;
      return {{left: parseFloat(pop.left), top: parseFloat(pop.top), box: browser.element('coach-box').style.zIndex}};
    """)
    result = seen["result"]

    assert result["left"] + 340 <= 620 - 14, f"the popover overlaps the note: {result}"
    assert result["left"] >= 200 and result["top"] == 434
    assert int(result["box"]) < 35

def test_the_note_opens_for_a_step_on_its_own_control_and_folds_again_when_the_step_moves_back(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      const folded = () => browser.element('lesson').classList.contains('hidden');
      const start = folded();
      {to("verify")}
      const atVerify = {{folded: folded(), check: document.querySelector('[data-tab="check"]').getAttribute('aria-selected')}};
      await browser.click('coach-pop-back');
      return {{start, atVerify, back: folded()}};
    """)

    assert seen["result"] == {"start": True, "atVerify": {"folded": False, "check": "true"}, "back": True}

def test_an_open_note_s_tab_follows_the_step(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      await browser.click('note-pill');
      await browser.click('[data-tab="hint"]');
      {to("rule")}
      const rule = document.querySelector('.tab[aria-selected="true"]').dataset.tab;
      {to("verify")}
      const verify = document.querySelector('.tab[aria-selected="true"]').dataset.tab;
      await browser.click('coach-pop-back');
      return {{rule, verify, retry: document.querySelector('.tab[aria-selected="true"]').dataset.tab,
              open: !browser.element('lesson').classList.contains('hidden')}};
    """)

    assert seen["result"] == {"rule": "steps", "verify": "check", "retry": "steps", "open": True}

INSECURE = """
const selected = [];
Object.getPrototypeOf(document.body).select = function () { selected.push(this.value); };
document.execCommand = (command) => command === 'copy' && selected.length > 0;
"""

def test_copy_falls_back_to_a_selection_when_the_page_is_not_a_secure_context(client):
    seen = open_page(client, "/blue/1/", setup=coached() + INSECURE, scenario=f"""
      {to("exclude")}
      await browser.click('coach-pop-copy');
      return {{selected, said: browser.text('coach-pop-copy'), left: document.querySelectorAll('textarea').length}};
    """)

    assert seen["result"] == {"selected": [COMMAND["exclude"]], "said": english("lesson.copied"), "left": 0}

def test_copy_says_it_failed_when_neither_way_works(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("exclude")}
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
    seen = open_page(client, "/blue/1/", setup=coached() + WAF_TERMINAL, scenario=f"""
      await browser.click('[data-pane="waf"]');
      {to("exclude")}
      await browser.click('coach-pop-run');
      return {{pasted, entered, said: browser.text('coach-pop-typed')}};
    """)
    result = seen["result"]

    assert result["pasted"] == [COMMAND["exclude"] + "\n"], "one paste, ending in a newline"
    assert result["entered"] == ["\r"], "Enter as well, since bash keeps a bracketed paste's newline as text"
    assert result["said"] == english("lesson.ran")

def test_run_in_terminal_opens_the_waf_terminal_first_when_another_pane_is_shown(client):
    seen = open_page(client, "/blue/1/", setup=coached() + WAF_TERMINAL, scenario=f"""
      {to("exclude")}
      await browser.click('coach-pop-run');
      return {{pasted: pasted.length, waf: document.querySelector('[data-pane="waf"]').getAttribute('aria-selected'),
              src: browser.element('pane-frame').getAttribute('src')}};
    """)

    assert seen["result"] == {"pasted": 1, "waf": "true", "src": "/vm-terminal/fsl-waf/"}

def test_the_alert_check_passes_on_a_new_blocked_o_brien_search_from_the_site_browser_only(client):
    seen = open_page(client, "/blue/1/", setup=coached() + """
      range.detections.push({id: 1, marker: 'browse', path: "/search/?q=O%27Brien"});
    """, scenario="""
      const poll = async () => { for (let i = 0; i < 5; i += 1) await browser.wait(1000); };
      await poll();
      const earlier = browser.text('coach-pop-title');
      range.detections.push({id: 4, marker: 'case-uuid', path: "/search/?q=O%27Brien"});
      await poll();
      const fromACase = browser.text('coach-pop-title');
      range.detections.push({id: 5, marker: 'browse', path: "/search/?q=release"});
      await poll();
      const otherSearch = browser.text('coach-pop-title');
      range.detections.push({id: 6, marker: 'browse', path: "/search/?q=O%27Brien"});
      await poll();
      await browser.wait(1500);
      return {earlier, fromACase, otherSearch, after: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'),
              polls: range.checked.length > 0 && range.checked.every((body) => body.poll === true),
              read: browser.requests.filter((r) => r.route.endsWith('/ingest/') || r.route.includes('/detections/')).length};
    """)
    result = seen["result"]

    assert result["earlier"] == english("lesson.board.label.search"), "an alert from before the step is not new"
    assert result["fromACase"] == result["otherSearch"] == english("lesson.board.label.search")
    assert result["after"] == english("lesson.board.label.find")
    assert result["said"] == english("lesson.board.line.search")
    assert result["polls"] is True, "a poll that finds nothing is not a wrong answer"
    assert result["read"] == 0, "the platform reads the records and judges; the page only asks"

def test_a_check_that_has_not_passed_yet_says_specifically_what_is_missing_in_its_status_line(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      const poll = async () => {{ for (let i = 0; i < 5; i += 1) await browser.wait(1000); }};
      await poll();
      const search = browser.text('coach-pop-status');
      await browser.click('[data-pane="waf"]');
      {to("exclude")}
      const fresh = browser.text('coach-pop-status');
      await poll();
      const exclude = browser.text('coach-pop-status');
      range.waf = {{paranoia: 4, version: "v3", exclusions: [{{rule_id: 920273, target: "ARGS:q", path: "/search/"}}]}};
      await poll();
      return {{search, fresh, exclude, reload: browser.text('coach-pop-status'), title: browser.text('coach-pop-title')}};
    """)
    result = seen["result"]

    assert result["search"] == english("lesson.board.fail.search")
    assert result["fresh"] == english("lesson.status.auto")
    assert result["exclude"] == english("lesson.board.fail.exclude")
    assert result["reload"] == english("lesson.board.fail.exclude.reload"), "the file has it, the WAF still blocks"
    assert result["title"] == english("lesson.board.label.exclude")

def test_the_waf_check_passes_once_the_file_holds_the_exclusion_and_the_o_brien_search_gets_through(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("exclude")}
      range.waf = {{paranoia: 4, version: "v3", exclusions: [{{rule_id: 920273, target: "ARGS:q", path: "/search/"}}]}};
      range.status = 200;
      for (let i = 0; i < 5; i += 1) await browser.wait(1000);
      await browser.wait(1500);
      return {{title: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'), fired: range.fired,
              sent: browser.requests.filter((r) => r.route === '/api/sessions/1/attacks/').length}};
    """)

    assert seen["result"] == {
        "title": english("lesson.board.label.retry"), "said": english("lesson.board.line.exclude"),
        "fired": ["board-normal-search-with-apostrophe"], "sent": 0,
    }, "the platform replays the O'Brien search for the check; the page sends no attack of its own"

def test_the_answer_check_explains_949110_and_accepts_920273(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("rule")}
      const submit = async (value) => {{
        document.querySelector('#coach-pop-act [data-act="value"]').value = value;
        document.querySelector('#coach-pop-act [data-act="answer"]').dispatchEvent({{type: 'submit', preventDefault() {{}}}});
        await browser.settle();
        return browser.text('coach-pop-said');
      }};
      const known = await submit('949110');
      const other = await submit('1234');
      await submit(' 920273 ');
      await browser.wait(1500);
      return {{known, other, title: browser.text('coach-pop-title'), said: browser.text('coach-pop-said')}};
    """)

    assert seen["result"] == {
        "known": english("lesson.board.wrong.rule.949110"), "other": english("lesson.check.wrong"),
        "title": english("lesson.board.label.target"), "said": english("lesson.board.line.rule"),
    }

def test_the_choice_check_offers_the_four_fields_and_takes_only_the_search_field(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("target")}
      const options = [...document.querySelectorAll('#coach-pop-act [data-act="choose"]')];
      const labels = options.map((o) => o.textContent);
      document.querySelector('#coach-pop-act [data-value="REQUEST_URI"]').click();
      await browser.settle();
      const wrong = browser.text('coach-pop-title');
      document.querySelector('#coach-pop-act [data-value="ARGS:q"]').click();
      await browser.settle();
      await browser.wait(1500);
      return {{labels, wrong, after: browser.text('coach-pop-title')}};
    """)

    assert seen["result"]["labels"] == [
        english("lesson.board.option.target.ARGS:q"), english("lesson.board.option.target.REQUEST_URI"),
        english("lesson.board.option.target.REQUEST_COOKIES"), english("lesson.board.option.target.REQUEST_HEADERS"),
    ]
    assert seen["result"]["wrong"] == english("lesson.board.label.target")
    assert seen["result"]["after"] == english("lesson.board.label.exclude")

def test_the_served_check_runs_when_the_site_shows_the_o_brien_search_again(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("retry")}
      await browser.click('[data-pane="site"]');
      dispatchEvent({{type: 'message', data: {{fslSite: "/site/1/board.com/search/?q=O%27Brien"}}}});
      await browser.settle();
      const blocked = [browser.text('coach-pop-title'), browser.text('coach-pop-status')];
      range.status = 200;
      dispatchEvent({{type: 'message', data: {{fslSite: "/site/1/board.com/search/?q=O%27Brien"}}}});
      await browser.settle();
      await browser.wait(1500);
      return {{blocked, after: browser.text('coach-pop-title')}};
    """)

    assert seen["result"]["blocked"] == [english("lesson.board.label.retry"), english("lesson.board.fail.retry", 403)]
    assert seen["result"]["after"] == english("lesson.board.label.verify")

def test_the_verify_step_finishes_the_lesson_only_on_pass(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("verify")}
      await browser.click('lesson-verify');
      const failed = browser.text('coach-pop-said');
      range.passed = true;
      await browser.click('lesson-verify');
      const list = [...browser.element('lesson-step-list').querySelectorAll('[data-step]')];
      return {{failed, said: browser.text('coach-pop-said'), text: browser.text('coach-pop-text'),
              allDone: list.every((item) => item.textContent.includes('✓')),
              hint: browser.element('coach-pop-hint').classList.contains('hidden')}};
    """)

    assert seen["result"] == {
        "failed": english("lesson.board.fail.verify"), "said": english("lesson.board.line.verify"),
        "text": english("lesson.done"), "allDone": True, "hint": True,
    }

def test_a_minute_on_a_step_offers_a_hint_without_recording_one_and_each_press_climbs(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("rule")}
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
    assert result["one"] == {"help": english("lesson.board.nudge.rule"), "button": english("lesson.hint.more"), "doIt": False}
    assert english("lesson.board.answer.rule") in result["three"]["help"] and not result["three"]["doIt"]
    assert result["four"]["doIt"] is True
    assert (result["used"], result["level"]) == ([{"step": "rule", "level": "hint"}], 4)

def test_two_wrong_answers_raise_the_hint_a_level(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("target")}
      document.querySelector('#coach-pop-act [data-value="REQUEST_COOKIES"]').click();
      await browser.settle();
      const once = browser.text('coach-pop-help');
      document.querySelector('#coach-pop-act [data-value="REQUEST_HEADERS"]').click();
      await browser.settle();
      return {{once, twice: browser.text('coach-pop-help')}};
    """)

    assert seen["result"] == {"once": "", "twice": english("lesson.board.nudge.target")}

def test_do_it_for_me_performs_the_step_and_records_that_help_was_used(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("rule")}
      {hints(4)}
      await browser.click('coach-pop-do');
      await browser.wait(1500);
      return {{title: browser.text('coach-pop-title'), recorded: range.used,
              marked: browser.element('lesson-step-list').querySelector('[data-step="{at("rule")}"]').textContent}};
    """)
    result = seen["result"]

    assert result["title"] == english("lesson.board.label.target")
    assert result["recorded"] == [{"step": "rule", "level": "hint"}, {"step": "rule", "level": "do"}], (
        "help is recorded on the session through the API, once per step and kind"
    )
    assert english("lesson.helped") in result["marked"]

def test_do_it_for_me_on_the_terminal_step_has_the_platform_add_the_exclusion_and_types_nothing(client):
    seen = open_page(client, "/blue/1/", setup=coached() + WAF_TERMINAL, scenario=f"""
      {to("exclude")}
      {hints(4)}
      await browser.click('coach-pop-do');
      return {{pasted, puts: range.puts, asked: browser.requests.filter((r) => r.route.endsWith('/do/')).map((r) => r.route)}};
    """)

    assert seen["result"] == {"pasted": [], "puts": [{"paranoia": 4, "exclusions": [
        {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}]}],
        "asked": ["/api/sessions/1/lesson/steps/exclude/do/"]}, "the agent path: the platform adds it through the WAF API"

def test_do_it_for_me_on_the_terminal_step_moves_on_once_the_platform_s_check_passes(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {to("exclude")}
      {hints(4)}
      range.status = 200;
      await browser.click('coach-pop-do');
      await browser.wait(1500);
      return {{title: browser.text('coach-pop-title'), said: browser.text('coach-pop-said'), fired: range.fired,
              marked: browser.element('lesson-step-list').querySelector('[data-step="{at("exclude")}"]').textContent}};
    """)

    assert seen["result"]["title"] == english("lesson.board.label.retry")
    assert seen["result"]["said"] == english("lesson.board.line.exclude")
    assert seen["result"]["fired"] == ["board-normal-search-with-apostrophe"]
    assert english("lesson.helped") in seen["result"]["marked"]

def test_do_it_for_me_on_the_first_step_opens_the_search_in_the_site_browser(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      {hints(4)}
      await browser.click('coach-pop-do');
      return {{src: browser.element('site-frame').getAttribute('src'),
              site: document.querySelector('[data-pane="site"]').getAttribute('aria-selected')}};
    """)

    assert seen["result"] == {"src": "http://console.test:8002/site/1/board.com/search/?q=O'Brien", "site": "true"}

def test_the_do_it_yourself_path_drops_the_ready_made_filter_and_the_run_button(client):
    seen = open_page(client, "/blue/1/", setup=coached(), scenario=f"""
      browser.element('lesson-stretch').checked = true;
      browser.element('lesson-stretch').dispatchEvent({{type: 'change'}});
      {to("find")}
      const chip = document.querySelector('#coach-pop-act [data-act="chip"]');
      {to("exclude")}
      return {{chip: chip === null, run: browser.element('coach-pop-run').classList.contains('hidden'),
              code: !browser.element('coach-pop-code-box').classList.contains('hidden'),
              said: browser.text('coach-pop-typed'), kept: localStorage.getItem('fsl-lesson-stretch')}};
    """)

    assert seen["result"] == {"chip": True, "run": True, "code": True,
                              "said": english("lesson.stretch.type"), "kept": "true"}

EVERYWHERE = """
document.querySelectorAll('.pane-tab').forEach((tab, index) => {
  tab.getBoundingClientRect = () => ({left: 8, top: 60 + 50 * index, right: 52, bottom: 104 + 50 * index, width: 44, height: 44});
});
browser.element('site-address').getBoundingClientRect = () => ({left: 300, top: 60, right: 1300, bottom: 88, width: 1000, height: 28});
['[data-test-subj="docTableExpandToggleColumn"]', '[data-test-subj="field-rule"]',
 '[data-test-subj="field-transaction.messages.details.data"]'].forEach((selector) => present.add(selector));
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
          const opens = {{0: 'site', 1: 'elk', 2: 'elk', 3: 'elk', 4: 'waf', 5: 'site'}}[index];
          if (opens) await browser.click(`[data-pane="${{opens}}"]`);
          await browser.wait(16);
          visited.push({{stretch, index, first, then: {{drawn: !box.classList.contains('hidden'), target: box.dataset.target}}}});
        }}
      }}
      return visited;
    """)
    expected = {
        "search": "#site-address", "find": '[data-test-subj="docTableExpandToggleColumn"]',
        "rule": '[data-test-subj="field-rule"]', "target": '[data-test-subj="field-transaction.messages.details.data"]',
        "exclude": "pane", "retry": "#site-address", "verify": "#lesson-verify",
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
    assert seen["result"]["open"] == {"text": english("lesson.board.coach.search"), "target": "#site-address"}
    assert "http://board.com/search/?q=O'Brien" in english("lesson.board.coach.search")

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

def test_the_home_card_shows_the_lesson_s_goal_level_time_and_prerequisites_and_starts_each_rung(client):
    posted = []
    for rung in ('[data-mode="guided"]', '[data-mode="self"]', '[data-rung="wargame"]'):
        seen = open_page(client, "/", setup=CATALOGUE, scenario=f"""
          const card = browser.text('[data-lesson-card="waf-exclusion"]');
          await browser.click('{rung}');
          return {{card, posted: browser.requests.filter((r) => r.method === 'POST').map((r) => r.body)}};
        """)
        assert seen["errors"] == []
        posted += seen["result"]["posted"]
    card = seen["result"]["card"]

    for shown in (english("lesson.board.title"), english("lesson.board.summary"), english("difficulty.easy"),
                  english("main.minutes", 40), english("main.lesson.needs_none"),
                  english("main.rung.guided"), english("main.rung.self"), english("main.rung.wargame")):
        assert shown in card, shown
    assert posted == [
        {"scenario": "board", "guidance": True, "lesson": "waf-exclusion", "defense": "minimal"},
        {"scenario": "board", "guidance": True, "lesson": "waf-exclusion", "mode": "self", "defense": "minimal"},
        {"scenario": "board"},
    ], "lesson and practice run the same lesson; the wargame rung runs without guidance on the full defense"

def test_practice_hides_the_steps_the_hints_and_the_coach_and_keeps_the_goal_and_check_tabs(client):
    seen = open_page(client, "/blue/1/", setup=guided(True) + """
      range.mode = "self";
    """, scenario="""
      await browser.click('note-pill');
      const tabs = [...document.querySelectorAll('#lesson-tabs .tab')]
        .filter((tab) => !tab.classList.contains('hidden')).map((tab) => tab.dataset.tab);
      const shown = [...document.querySelectorAll('[data-pane-of]')]
        .filter((pane) => !pane.classList.contains('hidden')).map((pane) => pane.dataset.paneOf);
      return {tabs, shown, pop: browser.element('coach-pop').classList.contains('hidden'),
              why: document.querySelectorAll('#lesson-theory [data-shows]').length,
              note: browser.text('lesson-mode-note'),
              stepped: browser.requests.filter((r) => r.route.includes('/lesson/steps/')).length};
    """)

    assert seen["errors"] == []
    assert seen["result"]["tabs"] == ["goal", "theory", "check"]
    assert seen["result"]["shown"] == ["goal"]
    assert seen["result"]["pop"] is True and seen["result"]["stepped"] == 0, "no coach walks a practice run"
    assert seen["result"]["why"] == 0
    assert seen["result"]["note"] == english("lesson.mode.self")

def test_the_mode_switch_patches_the_session_s_mode(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('lesson-mode');
      return {patched: range.patched, label: browser.text('lesson-mode')};
    """)

    assert seen["result"] == {"patched": {"mode": "self"}, "label": english("lesson.mode.to_self")}
