import json
import re

import pytest

import wargames
from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

STEPS = wargames.lesson("board")["steps"]
IDS = [step["id"] for step in STEPS]
COMMAND = {step["id"]: step.get("command", "") for step in STEPS}

GUIDED = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: GUIDANCE, waf_box: "fsl-1-waf",
                   waf_rules: "/etc/modsecurity.d/owasp-crs/rules", lesson: GUIDANCE ? {
      text: "lesson.board",
      cases: ["board-sqli-orderby-sqlmap", "board-normal-search-with-apostrophe"],
      steps: STEPS_JSON,
    } : null}};
  }
  if (request.route === "/api/sessions/1/waf/" && request.method === "GET") {
    return {body: {paranoia: 4, exclusions: [], version: "v1"}};
  }
  if (request.route === "/api/sessions/1/verify/") {
    return {body: {passed: false, run: "r", cases: [
      {name: "board-sqli-orderby-sqlmap", malicious: true, outcome: "held"},
      {name: "board-normal-search-with-apostrophe", malicious: false, outcome: "blocked"},
    ], diagnosis: [
      ["lesson.diag.blocked_ratio", [1, 1]],
      ["lesson.diag.benign_blocked", ["board-normal-search-with-apostrophe", 403]],
    ]}};
  }
  return {status: 404, body: {detail: "not served"}};
});
""".replace("STEPS_JSON", json.dumps(STEPS))

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
    assert shown["result"]["frame"] == "/kibana/", "Kibana stays the pane under the note"
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

    assert seen["result"]["opened"] == {"note": True, "pill": False, "kept": {"open": True, "tab": "steps"}}
    assert seen["result"]["folded"] == {"note": False, "pill": True, "kept": {"open": False, "tab": "steps"}}
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

def test_a_remembered_open_note_and_tab_are_restored_on_the_next_visit(client):
    seen = open_page(client, "/blue/1/", setup=guided(True) + """
      localStorage.setItem('fsl-lesson-note', JSON.stringify({open: true, tab: 'theory'}));
    """, scenario="""
      return {note: browser.element('lesson').classList.contains('hidden'),
              theory: document.querySelector('[data-pane-of="theory"]').classList.contains('hidden')};
    """)

    assert seen["result"] == {"note": False, "theory": False}

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
              writes: browser.requests.filter((r) => r.method !== 'GET').map((r) => r.route)};
    """)

    assert seen["result"]["cards"] == ["why_rule", "why_target", "why_file"]
    assert english("lesson.board.hint.why_rule.title") in seen["result"]["hints"]
    assert "nginx" not in seen["result"]["hints"], "a hint says why, the steps say what to type"
    assert seen["result"]["folded"] is True and seen["result"]["opened"] is True
    assert "ctl:ruleRemoveTargetById=920273;ARGS:q" in seen["result"]["answer"]
    assert "nginx -t && nginx -s reload" in seen["result"]["answer"]
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
              asked: browser.requests.filter((r) => r.method === 'POST').map((r) => r.route)};
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
      return browser.requests.filter((r) => r.method === 'POST').map((r) => [r.route, r.body]);
    """)

    assert seen["result"] == [[
        "/api/sessions/1/attacks/", {"case": "board-normal-search-with-apostrophe"},
    ]]

CATALOGUE = """
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [
      {id: "board", name: "Board", description: "", cases: 1, lesson: true},
      {id: "corp", name: "Corp", description: "", cases: 1, lesson: false},
    ]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 9}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_only_a_scenario_with_a_lesson_offers_to_start_as_one_and_it_opens_a_guided_minimal_session(client):
    seen = open_page(client, "/", setup=CATALOGUE, scenario="""
      const lessons = [...document.querySelectorAll('[data-lesson]')].map((b) => b.dataset.wargame);
      await browser.click('[data-lesson="true"]');
      return {lessons, posted: browser.requests.filter((r) => r.method === 'POST').map((r) => r.body)};
    """)

    assert seen["errors"] == []
    assert seen["result"]["lessons"] == ["board"]
    assert seen["result"]["posted"] == [{"scenario": "board", "guidance": True, "defense": "minimal"}]

def test_the_catalogue_says_which_scenario_carries_a_lesson(client):
    listed = {w["id"]: w["lesson"] for w in client.get("/api/wargames/").json()}

    assert listed == {"board": True, "corp": False}

KIBANA_TABLE = '[data-test-subj="discoverDocTable"]'

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
browser.element('lesson-replay').getBoundingClientRect =
  () => ({left: 1100, top: 300, right: 1180, bottom: 330, width: 80, height: 30});
"""

def coached(guidance):
    return COACHED.replace("GUIDED_FLAG", "true" if guidance else "false")

def at(step):
    return IDS.index(step)

def test_the_coach_boxes_a_kibana_element_while_it_is_on_screen_and_hides_when_it_is_not(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      const box = () => browser.element('coach-box');
      await browser.wait(16);
      const before = box().classList.contains('hidden');
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      const over = {{hidden: box().classList.contains('hidden'), left: box().style.left, top: box().style.top,
                    width: box().style.width, layer: box().style.zIndex, scrim: box().classList.contains('scrim'),
                    events: box().style.pointerEvents}};
      present.clear();
      await browser.wait(16);
      return {{before, over, after: box().classList.contains('hidden')}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["before"] is True
    assert seen["result"]["over"] == {
        "hidden": False, "left": "206px", "top": "66px", "width": "108px", "layer": "40", "scrim": True,
        "events": "none",
    }, "the box sits over the element, offset by where the Kibana pane is, and never takes a click"
    assert seen["result"]["after"] is True

def test_the_popover_names_the_step_says_what_to_do_and_shows_the_progress(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      return {{hidden: browser.element('coach-pop').classList.contains('hidden'),
              count: browser.text('coach-pop-count'), title: browser.text('coach-pop-title'),
              text: browser.text('coach-pop-text'),
              command: browser.element('coach-pop-command').classList.contains('hidden'),
              dots: browser.element('coach-pop-dots').querySelectorAll('.dot').length,
              lit: browser.element('coach-pop-dots').querySelectorAll('.dot-blue').length,
              buttons: [browser.text('coach-pop-back'), browser.text('coach-pop-next')],
              back: browser.element('coach-pop-back').disabled}};
    """)

    assert seen["result"] == {
        "hidden": False, "count": f"1 / {len(STEPS)}", "title": english("lesson.board.label.alerts"),
        "text": english("lesson.board.coach.alerts"), "command": True, "dots": len(STEPS), "lit": 1,
        "buttons": [english("lesson.coach.back"), english("lesson.coach.next")], "back": True,
    }, "a Kibana step is a click, so it carries no command block"

def test_the_popover_sits_below_its_target_or_above_it_when_there_is_no_room(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      const pop = browser.element('coach-pop').style;
      const arrow = browser.element('coach-pop-arrow');
      const roomy = {{top: pop.top, arrowTop: arrow.style.top, arrow: arrow.classList.contains('hidden')}};
      pane.getBoundingClientRect = () => ({{left: 200, top: 50, right: 1000, bottom: 900, width: 800, height: 850}});
      table.getBoundingClientRect = () => ({{left: 10, top: 700, right: 110, bottom: 740, width: 100, height: 40}});
      await browser.wait(16);
      return {{roomy, cramped: {{top: pop.top, arrowBottom: arrow.style.bottom}}}};
    """)

    assert seen["result"]["roomy"] == {"top": "124px", "arrowTop": "-6px", "arrow": False}, (
        "below the target (bottom at 110px) with a 14px gap, the arrow pointing up at it"
    )
    assert seen["result"]["cramped"] == {"top": "536px", "arrowBottom": "-6px"}, (
        "above the target (top at 750px, popover 200px tall, 14px gap) when below would leave the window"
    )

def test_the_coach_walks_on_to_the_lesson_note_s_own_controls_and_opens_the_check_tab(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      for (let i = 0; i < {at("replay")}; i += 1) await browser.click('coach-pop-next');
      await browser.wait(16);
      const box = browser.element('coach-box');
      return {{text: browser.text('lesson-coach-text'), left: box.style.left, layer: box.style.zIndex,
              title: browser.text('coach-pop-title'), events: box.style.pointerEvents,
              note: browser.element('lesson').classList.contains('hidden'),
              check: document.querySelector('[data-pane-of="check"]').classList.contains('hidden')}};
    """)

    assert seen["result"] == {
        "text": english("lesson.board.coach.replay"), "left": "1096px", "layer": "9999",
        "title": english("lesson.board.label.replay"), "events": "none", "note": False, "check": False,
    }, "a step on a note control opens the note at the tab that holds it and boxes the control above the note"

def test_the_coach_says_where_to_look_when_the_element_never_appears(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      const hidden = () => [browser.element('lesson-coach-missing').classList.contains('hidden'),
                            browser.element('coach-pop-missing').classList.contains('hidden')];
      const early = hidden();
      for (let i = 0; i < 130; i += 1) await browser.wait(16);
      return {early, late: hidden(), pop: browser.element('coach-pop').classList.contains('hidden')};
    """)

    assert seen["result"] == {"early": [True, True], "late": [False, False], "pop": False}, (
        "with no target the popover stays, unanchored, and says so"
    )

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

def test_clicking_the_highlighted_kibana_element_moves_the_guide_on(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + CLICKABLE_KIBANA, scenario=f"""
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      const before = browser.text('coach-pop-text');
      const heard = listeners.filter((l) => l.type === 'click' && l.capture === true);
      heard.forEach((l) => l.listener({{target: {{}}}}));
      await browser.wait(1);
      const missed = browser.text('coach-pop-text');
      heard.forEach((l) => l.listener({{target: table.inner}}));
      await browser.wait(1);
      return {{before, missed, after: browser.text('coach-pop-text'), heard: heard.length}};
    """)

    assert seen["result"]["heard"] == 1, "the guide listens in the Kibana document in the capture phase"
    assert seen["result"]["before"] == english("lesson.board.coach.alerts")
    assert seen["result"]["missed"] == english("lesson.board.coach.alerts"), "a click elsewhere does not advance"
    assert seen["result"]["after"] == english("lesson.board.coach.expand")

def test_clicking_the_highlighted_note_control_moves_the_guide_on(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      for (let i = 0; i < {at("replay")}; i += 1) await browser.click('lesson-coach-next');
      const before = browser.text('lesson-coach-text');
      await browser.click('lesson-verify');
      await browser.click('lesson-replay');
      await browser.wait(1);
      return {{before, after: browser.text('lesson-coach-text')}};
    """)

    assert seen["result"]["before"] == english("lesson.board.coach.replay")
    assert seen["result"]["after"] == english("lesson.board.coach.verify"), (
        "only a click on the highlighted control advances, after the click has gone through"
    )

def test_the_steps_tab_leads_with_the_current_step_and_lists_every_step(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      await browser.click('note-pill');
      await browser.click('lesson-coach-next');
      const listed = [...browser.element('lesson-step-list').querySelectorAll('[data-step]')];
      return {count: browser.text('lesson-coach-count'), text: browser.text('lesson-coach-text'),
              listed: listed.length, done: listed[0].textContent.includes('✓'),
              goal: browser.text('lesson-goal'), scrolls: browser.element('lesson-body').classList.contains('overflow-y-auto')};
    """)

    assert seen["result"] == {
        "count": english("lesson.coach.count", 2, len(STEPS)), "text": english("lesson.board.coach.expand"),
        "listed": len(STEPS), "done": True, "goal": english("lesson.board.summary"), "scrolls": True,
    }

def test_a_step_in_the_list_jumps_the_guide_there(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      await browser.click('[data-step="{at("edit")}"]');
      return browser.text('coach-pop-title');
    """)

    assert seen["result"] == english("lesson.board.label.edit")

def test_the_step_reached_is_kept_per_session_and_resumed_on_the_next_visit(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + f"""
      localStorage.setItem('fsl-lesson-step-1', '{at("apply") + 1}');
    """, scenario="""
      const resumed = browser.text('coach-pop-title');
      await browser.click('coach-pop-next');
      return {resumed, kept: localStorage.getItem('fsl-lesson-step-1')};
    """)

    assert seen["result"] == {"resumed": english("lesson.board.label.apply"), "kept": str(at("apply") + 2)}

def test_closing_the_popover_hides_the_guide_until_the_steps_tab_brings_it_back(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
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
              expanded: browser.element('lesson-theory').querySelector('[data-card="scoring"]')
                .getAttribute('aria-expanded'),
              text: body.textContent};
    """)
    plain = open_page(client, "/blue/1/", setup=guided(False), scenario="""
      return browser.element('lesson-theory').querySelectorAll('[data-card]').length;
    """)

    assert shown["errors"] == []
    assert shown["result"]["ids"] == ["paranoia", "scoring", "culprit", "fixes", "anatomy"]
    assert all(shown["result"]["folded"]), "the note stays compact until a card is asked for"
    assert shown["result"]["opened"] is True and shown["result"]["expanded"] == "true"
    assert english("lesson.board.theory.scoring.body") in shown["result"]["text"]
    assert plain["result"] == 0, "an unguided session teaches nothing"

def test_a_theory_card_points_the_coach_at_what_it_talks_about(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      await browser.click('[data-card="anatomy"]');
      await browser.click('[data-shows="edit"]');
      const anatomy = browser.text('lesson-coach-text');
      await browser.click('[data-card="culprit"]');
      await browser.click('[data-shows="rule"]');
      return {anatomy, culprit: browser.text('lesson-coach-text')};
    """)

    assert seen["result"] == {
        "anatomy": english("lesson.board.coach.edit"),
        "culprit": english("lesson.board.coach.rule"),
    }

def test_the_coach_sends_the_learner_to_the_waf_pane_to_tune(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + """
      document.querySelector('.pane-tab[data-pane="waf"]').getBoundingClientRect =
        () => ({left: 8, top: 120, right: 52, bottom: 164, width: 44, height: 44});
    """, scenario=f"""
      for (let i = 0; i < {at("waf")}; i += 1) await browser.click('coach-pop-next');
      await browser.wait(16);
      const atWaf = {{text: browser.text('coach-pop-text'), left: browser.element('coach-box').style.left}};
      await browser.click('[data-pane="waf"]');
      await browser.wait(1);
      return {{atWaf, after: browser.text('coach-pop-text'),
              banner: browser.element('waf-banner').classList.contains('hidden'),
              box: browser.text('waf-box'), rules: browser.text('waf-rules')}};
    """)

    assert seen["result"]["atWaf"] == {"text": english("lesson.board.coach.waf"), "left": "4px"}
    assert seen["result"]["after"] == english("lesson.board.coach.audit"), (
        "opening the WAF pane is the click that moves the guide on"
    )
    assert seen["result"]["banner"] is False
    assert (seen["result"]["box"], seen["result"]["rules"]) == ("fsl-1-waf", "/etc/modsecurity.d/owasp-crs/rules/"), (
        "the WAF banner names only the box and where the CRS setup lives"
    )

def test_a_terminal_step_boxes_the_pane_and_its_popover_gives_the_exact_command(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      for (let i = 0; i < {at("edit")}; i += 1) await browser.click('coach-pop-next');
      await browser.wait(16);
      const box = browser.element('coach-box');
      const edit = {{title: browser.text('coach-pop-title'), text: browser.text('coach-pop-text'),
                    code: browser.text('coach-pop-code'), does: browser.text('coach-pop-does'),
                    shown: !browser.element('coach-pop-command').classList.contains('hidden'),
                    wide: browser.element('coach-pop').classList.contains('pop-wide'),
                    left: box.style.left, top: box.style.top, width: box.style.width, layer: box.style.zIndex,
                    scrim: box.classList.contains('scrim'),
                    popLeft: browser.element('coach-pop').style.left, popTop: browser.element('coach-pop').style.top,
                    arrow: browser.element('coach-pop-arrow').classList.contains('hidden')}};
      await browser.click('coach-pop-next');
      await browser.wait(16);
      const apply = {{text: browser.text('coach-pop-text'), code: browser.text('coach-pop-code'),
                     does: browser.text('coach-pop-does')}};
      return {{edit, apply}};
    """)
    edit, apply = seen["result"]["edit"], seen["result"]["apply"]

    assert seen["errors"] == []
    assert (edit["title"], edit["text"]) == (english("lesson.board.label.edit"), english("lesson.board.coach.edit"))
    assert edit["code"] == COMMAND["edit"] and "<<'EOF'" in edit["code"]
    assert edit["does"] == english("lesson.board.does.edit") and edit["shown"] and edit["wide"]
    assert (edit["left"], edit["top"], edit["width"], edit["layer"], edit["scrim"]) == (
        "196px", "46px", "808px", "40", False,
    ), "a step inside the terminal boxes the whole pane, without dimming it"
    assert (edit["popLeft"], edit["popTop"], edit["arrow"]) == ("644px", "434px", True), (
        "the popover sits in the pane's bottom right corner, clear of the output at the top"
    )
    assert apply == {"text": english("lesson.board.coach.apply"), "code": "nginx -t && nginx -s reload",
                     "does": english("lesson.board.does.apply")}

def test_the_copy_button_puts_the_step_s_command_on_the_clipboard(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + """
      const copied = [];
      navigator.clipboard = {writeText: async (text) => { copied.push(text); }};
    """, scenario=f"""
      for (let i = 0; i < {at("apply")}; i += 1) await browser.click('coach-pop-next');
      await browser.click('coach-pop-copy');
      return {{copied, said: browser.text('coach-pop-copy')}};
    """)

    assert seen["result"] == {"copied": ["nginx -t && nginx -s reload"], "said": english("lesson.copied")}

def test_kibana_s_first_visit_callouts_are_marked_seen_before_the_pane_loads(client):
    seen = open_page(client, "/blue/1/", setup=coached(False), scenario="""
      return ['discover:docExplorerUpdateCalloutClosed', 'discover:docExplorerCalloutClosed',
              'data.noDataPopover'].map((key) => localStorage.getItem(key));
    """)

    assert seen["result"] == ["true", "true", "true"], (
        "Kibana reads these with JSON.parse from the same-origin localStorage and "
        "hides the Discover tour callout and the no-data popover when they are true"
    )
