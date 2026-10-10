import re

import pytest

from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

GUIDED = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: GUIDANCE, lesson: GUIDANCE ? {
      text: "lesson.board",
      cases: ["board-sqli-orderby-sqlmap", "board-normal-search-with-apostrophe"],
    } : null}};
  }
  if (request.route === "/api/sessions/1/waf/" && request.method === "GET") {
    return {body: {paranoia: 4, exclusions: [], version: "v1"}};
  }
  if (request.route === "/api/sessions/1/waf/" && request.method === "PUT") {
    return {body: request.body};
  }
  if (request.route === "/api/sessions/1/verify/") {
    return {body: {passed: false, run: "r", cases: [], diagnosis: [
      ["lesson.diag.blocked_ratio", [2, 2]],
      ["lesson.diag.benign_blocked", ["board-normal-search-with-apostrophe", 403]],
    ]}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def guided(guidance):
    return GUIDED.replace("GUIDANCE", "true" if guidance else "false")

def test_the_lesson_panel_shows_beside_the_tools_only_in_a_guided_session(client):
    shown = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      return {
        hidden: browser.element('lesson').classList.contains('hidden'),
        steps: browser.text('lesson-steps'),
        hint: browser.text('lesson-hint'),
        frame: browser.element('pane-frame').getAttribute('src'),
      };
    """)
    plain = open_page(client, "/blue/1/", setup=guided(False), scenario="""
      return {hidden: browser.element('lesson').classList.contains('hidden'),
              routes: browser.requests.map((r) => r.route)};
    """)

    assert shown["errors"] == [] and plain["errors"] == []
    assert shown["result"]["hidden"] is False
    assert english("lesson.board.read") in shown["result"]["steps"]
    assert "ctl:ruleRemoveTargetById=920273;ARGS:q" in shown["result"]["hint"]
    assert "nginx -t" in shown["result"]["hint"] and "nginx -s reload" in shown["result"]["hint"]
    assert shown["result"]["frame"] == "/kibana/", "Kibana stays beside the lesson"
    assert plain["result"]["hidden"] is True
    assert "/api/sessions/1/waf/" not in plain["result"]["routes"]

def test_the_note_holds_no_tuning_form_and_shows_the_answer_until_the_learner_hides_it(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      const hidden = () => browser.element('lesson-hint').classList.contains('hidden');
      const first = {hidden: hidden(), toggle: browser.text('lesson-hint-toggle')};
      await browser.click('lesson-hint-toggle');
      const folded = {hidden: hidden(), toggle: browser.text('lesson-hint-toggle')};
      await browser.click('lesson-hint-toggle');
      return {first, folded, again: hidden(),
              form: ['lesson-paranoia', 'lesson-exclusions', 'lesson-save']
                .map((id) => document.getElementById(id)),
              writes: browser.requests.filter((r) => r.method !== 'GET').map((r) => r.route)};
    """)

    assert seen["result"]["form"] == [None, None, None], "the tuning is done in the WAF terminal"
    assert seen["result"]["first"] == {"hidden": False, "toggle": english("lesson.hint.hide")}, (
        "the complete answer shows first"
    )
    assert seen["result"]["folded"] == {"hidden": True, "toggle": english("lesson.hint.show")}
    assert seen["result"]["again"] is False
    assert seen["result"]["writes"] == []

def test_verify_shows_the_verdict_and_the_reasons_in_plain_words(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.click('lesson-verify');
      return {verdict: browser.text('lesson-verdict'), why: browser.text('lesson-diagnosis'),
              asked: browser.requests.filter((r) => r.method === 'POST').map((r) => r.route)};
    """)

    assert seen["result"]["asked"] == ["/api/sessions/1/verify/"]
    assert seen["result"]["verdict"] == english("lesson.verify.fail")
    assert english("lesson.diag.benign_blocked", "board-normal-search-with-apostrophe", 403) \
        in seen["result"]["why"]
    assert not re.search(r"\b(TP|FP|FN|TN)\b", seen["result"]["why"]), (
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

def test_the_coach_boxes_a_kibana_element_while_it_is_on_screen_and_hides_when_it_is_not(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      const box = () => browser.element('coach-box').style;
      await browser.wait(16);
      const before = box().display;
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      const over = {{display: box().display, left: box().left, top: box().top, width: box().width,
                    layer: box().zIndex}};
      present.clear();
      await browser.wait(16);
      return {{before, over, after: box().display}};
    """)

    assert seen["errors"] == []
    assert seen["result"]["before"] == "none"
    assert seen["result"]["over"] == {
        "display": "", "left": "206px", "top": "66px", "width": "108px", "layer": "40",
    }, (
        "the box sits over the element, offset by where the Kibana pane is"
    )
    assert seen["result"]["after"] == "none"

def test_the_coach_walks_on_to_the_lesson_panel_s_own_controls(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      for (let i = 0; i < 10; i += 1) await browser.click('lesson-coach-next');
      await browser.wait(16);
      const box = browser.element('coach-box').style;
      return {text: browser.text('lesson-coach-text'), display: box.display, left: box.left, layer: box.zIndex,
              tag: browser.text('coach-tag-text'), events: box.pointerEvents};
    """)

    assert seen["result"]["text"] == english("lesson.board.coach.replay")
    assert seen["result"]["display"] == "" and seen["result"]["left"] == "1096px"
    assert seen["result"]["tag"] == "↓ " + english("lesson.board.label.replay"), (
        "the label carries the step's own short instruction, above the control"
    )
    assert seen["result"]["events"] == "none", "the overlay must never take a click"
    assert seen["result"]["layer"] == "9999", "a box on a note control is drawn above the note"

def test_the_coach_says_where_to_look_when_the_element_never_appears(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      const hidden = () => browser.element('lesson-coach-missing').classList.contains('hidden');
      const early = hidden();
      for (let i = 0; i < 130; i += 1) await browser.wait(16);
      return {early, late: hidden()};
    """)

    assert seen["result"] == {"early": True, "late": False}

def test_an_unguided_session_draws_no_coach(client):
    seen = open_page(client, "/blue/1/", setup=coached(False), scenario="""
      await browser.wait(16);
      return document.getElementById('coach-box') === null;
    """)

    assert seen["errors"] == [] and seen["result"] is True

def test_the_label_says_the_step_and_sits_above_the_target_or_below_it_when_there_is_no_room(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario=f"""
      present.add({KIBANA_TABLE!r});
      await browser.wait(16);
      const tag = browser.element('coach-tag');
      const text = browser.element('coach-tag-text');
      const roomy = {{text: text.textContent, top: tag.style.top}};
      pane.getBoundingClientRect = () => ({{left: 200, top: 0, right: 1000, bottom: 600, width: 800, height: 600}});
      table.getBoundingClientRect = () => ({{left: 10, top: 4, right: 110, bottom: 44, width: 100, height: 40}});
      await browser.wait(16);
      return {{roomy, cramped: {{text: text.textContent, top: tag.style.top}}}};
    """)

    label = english("lesson.board.label.alerts")
    assert seen["result"]["roomy"] == {"text": "↓ " + label, "top": "32px"}, (
        "above the box (target at 70px, label 30px tall, 8px gap), never over the target"
    )
    assert seen["result"]["cramped"] == {"text": "↑ " + label, "top": "52px"}

def test_the_lesson_note_minimizes_to_its_header_and_expands_again(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      const body = () => browser.element('lesson-body').classList.contains('hidden');
      const open = body();
      await browser.click('lesson-collapse');
      const folded = {hidden: body(), label: browser.text('lesson-collapse'),
                      floating: browser.element('lesson').style.position,
                      kept: JSON.parse(localStorage.getItem('fsl-lesson-note')).collapsed};
      await browser.click('lesson-collapse');
      return {open, folded, reopened: body()};
    """)

    assert seen["errors"] == []
    assert seen["result"]["open"] is False
    assert seen["result"]["folded"] == {
        "hidden": True, "label": english("lesson.note.expand"), "floating": "fixed", "kept": True,
    }, "a folded note is its header only, still floating over the pane"
    assert seen["result"]["reopened"] is False

def test_dragging_the_note_by_its_header_floats_it_there_and_remembers_the_place(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + """
      browser.element('lesson').getBoundingClientRect =
        () => ({left: 1000, top: 40, right: 1384, bottom: 840, width: 384, height: 800});
    """, scenario="""
      const header = browser.element('lesson-header');
      header.dispatchEvent({type: 'pointerdown', clientX: 1010, clientY: 50, pointerId: 1});
      header.dispatchEvent({type: 'pointermove', clientX: 410, clientY: 250, pointerId: 1});
      header.dispatchEvent({type: 'pointerup', clientX: 410, clientY: 250, pointerId: 1});
      await browser.settle();
      const style = browser.element('lesson').style;
      return {position: style.position, left: style.left, top: style.top, room: style.maxHeight,
              kept: JSON.parse(localStorage.getItem('fsl-lesson-note')),
              dock: browser.element('lesson-dock').classList.contains('hidden'),
              frame: browser.element('pane-frame').style.pointerEvents};
    """)

    assert seen["result"]["position"] == "fixed"
    assert (seen["result"]["left"], seen["result"]["top"]) == ("400px", "240px")
    assert seen["result"]["room"] == "min(26rem, calc(100vh - 240px - 1rem))", (
        "a moved note keeps its compact height and scrolls inside the window"
    )
    assert (seen["result"]["kept"]["left"], seen["result"]["kept"]["top"]) == (400, 240)
    assert seen["result"]["dock"] is False, "a moved note offers to dock again"
    assert seen["result"]["frame"] == "", "the Kibana frame takes clicks again after the drag"

def test_a_remembered_place_and_fold_are_restored_on_the_next_visit(client):
    seen = open_page(client, "/blue/1/", setup=coached(True) + """
      localStorage.setItem('fsl-lesson-note', JSON.stringify({collapsed: true, left: 120, top: 90}));
    """, scenario="""
      const style = browser.element('lesson').style;
      return {left: style.left, top: style.top,
              folded: browser.element('lesson-body').classList.contains('hidden')};
    """)

    assert seen["result"] == {"left": "120px", "top": "90px", "folded": True}

def test_a_coach_step_on_a_panel_control_unfolds_a_minimized_note(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      await browser.click('lesson-collapse');
      for (let i = 0; i < 10; i += 1) await browser.click('lesson-coach-next');
      return browser.element('lesson-body').classList.contains('hidden');
    """)

    assert seen["result"] is False

def test_kibana_s_first_visit_callouts_are_marked_seen_before_the_pane_loads(client):
    seen = open_page(client, "/blue/1/", setup=coached(False), scenario="""
      return ['discover:docExplorerUpdateCalloutClosed', 'discover:docExplorerCalloutClosed',
              'data.noDataPopover'].map((key) => localStorage.getItem(key));
    """)

    assert seen["result"] == ["true", "true", "true"], (
        "Kibana reads these with JSON.parse from the same-origin localStorage and "
        "hides the Discover tour callout and the no-data popover when they are true"
    )

def test_the_lesson_note_floats_over_the_pane_in_its_corner_and_reserves_no_column(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      const note = browser.element('lesson');
      const style = note.style;
      return {position: style.position, right: style.right, bottom: style.bottom, left: style.left,
              fixed: note.classList.contains('fixed'),
              dock: browser.element('lesson-dock').classList.contains('hidden')};
    """)

    assert seen["result"] == {
        "position": "fixed", "right": "1.5rem", "bottom": "1.5rem", "left": "",
        "fixed": True, "dock": True,
    }, "the note is layered above the full-width pane from the start, not a column beside it"

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
      const before = browser.text('lesson-coach-text');
      const heard = listeners.filter((l) => l.type === 'click' && l.capture === true);
      heard.forEach((l) => l.listener({{target: {{}}}}));
      await browser.wait(1);
      const missed = browser.text('lesson-coach-text');
      heard.forEach((l) => l.listener({{target: table.inner}}));
      await browser.wait(1);
      return {{before, missed, after: browser.text('lesson-coach-text'), heard: heard.length}};
    """)

    assert seen["result"]["heard"] == 1, "the guide listens in the Kibana document in the capture phase"
    assert seen["result"]["before"] == english("lesson.board.coach.alerts")
    assert seen["result"]["missed"] == english("lesson.board.coach.alerts"), "a click elsewhere does not advance"
    assert seen["result"]["after"] == english("lesson.board.coach.expand")

def test_clicking_the_highlighted_note_control_moves_the_guide_on(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      for (let i = 0; i < 10; i += 1) await browser.click('lesson-coach-next');
      const before = browser.text('lesson-coach-text');
      await browser.click('lesson-verify');
      await browser.click('lesson-replay');
      await browser.wait(1);
      return {before, after: browser.text('lesson-coach-text')};
    """)

    assert seen["result"]["before"] == english("lesson.board.coach.replay")
    assert seen["result"]["after"] == english("lesson.board.coach.verify"), (
        "only a click on the highlighted control advances, after the click has gone through"
    )

def test_the_note_leads_with_the_step_and_keeps_the_goal_to_one_line_until_asked(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      const steps = () => browser.element('lesson-steps').classList.contains('hidden');
      const folded = steps();
      await browser.click('lesson-goal-toggle');
      return {folded, opened: !steps(), goal: browser.text('lesson-goal'),
              toggle: browser.text('lesson-goal-toggle'),
              room: browser.element('lesson').style.maxHeight,
              scrolls: browser.element('lesson-body').classList.contains('overflow-y-auto')};
    """)

    assert seen["result"] == {
        "folded": True, "opened": True, "goal": english("lesson.board.summary"),
        "toggle": english("lesson.goal.less"), "room": "min(26rem, 70vh)", "scrolls": True,
    }


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
        () => ({left: 16, top: 120, right: 192, bottom: 156, width: 176, height: 36});
    """, scenario="""
      for (let i = 0; i < 4; i += 1) await browser.click('lesson-coach-next');
      await browser.wait(16);
      const at = {text: browser.text('lesson-coach-text'), left: browser.element('coach-box').style.left};
      await browser.click('[data-pane="waf"]');
      await browser.wait(1);
      return {at, after: browser.text('lesson-coach-text')};
    """)

    assert seen["result"]["at"] == {"text": english("lesson.board.coach.waf"), "left": "12px"}
    assert seen["result"]["after"] == english("lesson.board.coach.audit"), (
        "opening the WAF pane is the click that moves the guide on"
    )


def test_the_terminal_steps_box_the_pane_and_move_on_from_the_label_s_own_buttons(client):
    seen = open_page(client, "/blue/1/", setup=coached(True), scenario="""
      for (let i = 0; i < 5; i += 1) await browser.click('lesson-coach-next');
      await browser.wait(16);
      const box = browser.element('coach-box').style;
      const tag = browser.element('coach-tag');
      const at = {text: browser.text('lesson-coach-text'), left: box.left, top: box.top, width: box.width,
                  layer: box.zIndex, tagLayer: tag.style.zIndex, tag: browser.text('coach-tag-text'),
                  display: tag.style.display,
                  takes: tag.style.pointerEvents};
      const steps = [];
      for (const id of ['coach-tag-next', 'coach-tag-next', 'coach-tag-next', 'coach-tag-next', 'coach-tag-back']) {
        await browser.click(id);
        steps.push(browser.text('lesson-coach-text'));
      }
      return {at, steps, buttons: [browser.text('coach-tag-back'), browser.text('coach-tag-next')]};
    """)

    assert seen["errors"] == []
    assert seen["result"]["at"] == {
        "text": english("lesson.board.coach.audit"), "left": "196px", "top": "46px", "width": "808px",
        "layer": "40", "tagLayer": "9999", "tag": "↓ " + english("lesson.board.label.audit"),
        "display": "flex", "takes": "auto",
    }, "a step inside the terminal boxes the whole pane under the note; its label, which takes clicks, sits above"
    assert seen["result"]["steps"] == [english(f"lesson.board.coach.{step}") for step in
                                       ("view", "edit", "test", "reload", "test")]
    assert seen["result"]["buttons"] == [english("lesson.coach.back"), english("lesson.coach.next")]
