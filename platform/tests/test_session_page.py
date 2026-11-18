import re
from pathlib import Path

import pytest

from tests.browser import open_page, worded

TEMPLATES = Path(__file__).resolve().parents[1] / "console" / "templates" / "console"

pytestmark = pytest.mark.django_db

FOUNDATIONS = """[
  {id: "f1", title: "lesson.map.title", defense: "full", step_ids: ["entry", "route"]},
  {id: "f2", title: "lesson.http.title", defense: "full", step_ids: ["search"]},
  {id: "f3", title: "lesson.logs.title", defense: "full", step_ids: ["search"]},
  {id: "f4", title: "lesson.xss.title", defense: "xss-gap", step_ids: ["search"]},
  {id: "f5", title: "lesson.sqli.title", defense: "full", step_ids: ["sort", "error", "undetected", "sqlmap"]},
  {id: "f6", title: "lesson.miss.title", defense: "overbroad", step_ids: ["excluded", "dump"]},
]"""

COURSE = """
browser.serve((request) => {
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 2}};
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", guidance: true, kind: "lesson", ready: true,
      lesson_id: "f6", defense: "overbroad", lesson: {text: "lesson.miss", steps: []},
      started_at: "2026-10-18T09:00:00Z", ended_at: "2026-10-18T09:40:00Z",
      lessons: [{id: "f1", started_at: "2026-10-18T09:00:00Z"}, {id: "f5", started_at: "2026-10-18T09:10:00Z"},
                {id: "f6", started_at: "2026-10-18T09:25:00Z"}],
      course: [{id: "f1", steps: 2, passed: 2, skipped: 0, hints: 0}, {id: "f5", steps: 9, passed: 8, skipped: 1, hints: 0},
               {id: "f6", steps: 2, passed: 2, skipped: 0, hints: 0}],
      result: {objectives: {lost: 1, undetected: 1, total: 1}, scenario: null}}};
  }
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", name: "Board", public_url: "http://board.com", foundations: FOUNDATIONS}]};
  }
  if (request.route === "/api/wargames/board/objectives/") {
    return {body: [{key: "board-auth-user-admin", name: "Board admin account", difficulty: 4}]};
  }
  if (request.route === "/api/sessions/1/score/") {
    return {body: {tp: 1, fp: 0, fn: 1, tn: 1, warnings: [["score.warning.wrong_reason", "board-sqli-orderby-sqlmap"]],
      breaches: [{key: "board-auth-user-admin", difficulty: 4, detected: false}],
      per_case: [
        {name: "board-normal-search", malicious: false, detected: false, detections: 0, corroborated: null,
         lesson: "f1", step: null, seed: true},
        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, detections: 1, corroborated: false,
         lesson: "f5", step: "sqlmap", seed: false},
        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: false, detections: 0, corroborated: null,
         lesson: "f6", step: "dump", seed: false},
      ]}};
  }
  return {status: 404, body: {detail: "not served"}};
});
""".replace("FOUNDATIONS", FOUNDATIONS)

SHOWN = """
  return {cases: browser.text('case-rows'), judged: browser.text('judgement'), course: browser.text('course-rows'),
          line: browser.text('session-line'), lost: browser.text('lost-count'), restart: browser.text('restart')};
"""

def test_a_closed_course_names_each_run_by_lesson_and_step_and_never_by_case_id(client):
    seen = open_page(client, "/session/1/", setup=COURSE, scenario=SHOWN)
    shown = seen["result"]

    assert seen["errors"] == []
    assert not re.search(r"board-[a-z-]+", shown["cases"] + shown["judged"]), (
        "a learner reads case names, not the case file's ids")
    assert worded("session.run.step", 5, 4) in shown["cases"] and worded("session.run.step", 6, 2) in shown["cases"], (
        "the same sqlmap case ran in two lessons; each run says where it came from")
    assert worded("session.run.lesson", 1) in shown["cases"]
    assert shown["lost"] == "1 / 1" and worded("score.benign", 1, 1) in shown["judged"], (
        "both numbers stay on the page, side by side")
    assert worded("lesson.map.title") in shown["course"] and worded("lesson.miss.title") in shown["course"], (
        "after a course the page sums up every lesson taken, not only the last")
    assert worded("session.course.steps", 9, 8) in shown["course"]
    assert worded("wargame.board.name") not in shown["line"], "the breadcrumb already names the target"

F6_RUN = """        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: false, detections: 0, corroborated: null,
         lesson: "f6", step: "dump", seed: false},
"""
LOSS = 'breaches: [{key: "board-auth-user-admin", difficulty: 4, detected: false}],'

def test_a_lesson_switched_to_but_never_worked_on_is_not_listed_in_the_course(client):
    setup = COURSE.replace('{id: "f6", steps: 2, passed: 2, skipped: 0, hints: 0}', '{id: "f6", steps: 2, passed: 0, skipped: 0, hints: 0}')
    seen = open_page(client, "/session/1/", setup=setup, scenario=SHOWN)
    shown = seen["result"]

    assert seen["errors"] == []
    assert worded("lesson.sqli.title") in shown["course"] and worded("lesson.miss.title") not in shown["course"], (
        "the next lesson opens by itself after a lesson ends; opening it is not taking it")
    assert worded("lesson.miss.title") not in shown["line"]

def test_the_lesson_6_note_shows_only_when_lesson_6_ran_its_attack_or_an_objective_was_lost(client):
    def noted(setup):
        seen = open_page(client, "/session/1/", setup=setup, scenario="""
          await browser.wait(500);
          return !browser.element('score-lesson-lost').classList.contains('hidden');
        """)
        assert seen["errors"] == []
        return seen["result"]

    opened = COURSE.replace(LOSS, "breaches: [],").replace(F6_RUN, "")
    assert F6_RUN in COURSE and LOSS in COURSE
    assert noted(COURSE) is True
    assert noted(COURSE.replace(LOSS, "breaches: [],")) is True, "the run of step 2 is what the note explains"
    assert noted(opened) is False, "lesson 6 opened without its attack has nothing on purpose to explain"

def test_restarting_a_course_starts_its_first_lesson_with_that_lesson_s_defence(client):
    seen = open_page(client, "/session/1/", setup=COURSE, scenario="""
      const label = browser.text('restart');
      await browser.click('restart');
      return {label, posted: browser.requests.filter((r) => r.method === "POST" && r.route === "/api/sessions/")};
    """)

    assert seen["result"]["label"] == worded("session.restart"), "one name for the restart action"
    assert [request["body"] for request in seen["result"]["posted"]] == [
        {"scenario": "board", "guidance": True, "lesson": "f1", "defense": "full"}], (
        "restarting from F6 with F6's posture would open F1 on the overbroad WAF exclusion")

def restarted(client, setup):
    seen = open_page(client, "/session/1/", setup=setup, scenario="""
      const label = browser.text('restart');
      await browser.click('restart');
      return {label, posted: browser.requests.filter((r) => r.method === "POST" && r.route === "/api/sessions/")
        .map((r) => r.body)};
    """)
    assert seen["errors"] == []
    return seen["result"]

ONLY_F5 = COURSE.replace('{id: "f1", started_at: "2026-10-18T09:00:00Z"}, ', "").replace(
    '{id: "f1", steps: 2, passed: 2, skipped: 0, hints: 0}, ', "").replace(
    '{id: "f6", steps: 2, passed: 2, skipped: 0, hints: 0}', '{id: "f6", steps: 2, passed: 0, skipped: 0, hints: 0}')

def test_a_session_that_worked_only_lesson_5_restarts_lesson_5(client):
    shown = restarted(client, ONLY_F5)

    assert 'lessons: [{id: "f5"' in ONLY_F5 and 'course: [{id: "f5"' in ONLY_F5
    assert shown["label"] == worded("session.restart")
    assert shown["posted"] == [{"scenario": "board", "guidance": True, "lesson": "f5", "defense": "full"}], (
        "the console moved on to lesson 6 by itself; one lesson worked restarts that lesson")

def test_a_course_begun_at_lesson_5_restarts_from_lesson_5(client):
    shown = restarted(client, COURSE.replace('{id: "f1", started_at: "2026-10-18T09:00:00Z"}, ', "").replace(
        '{id: "f1", steps: 2, passed: 2, skipped: 0, hints: 0}, ', ""))

    assert shown["label"] == worded("session.restart")
    assert shown["posted"] == [{"scenario": "board", "guidance": True, "lesson": "f5", "defense": "full"}]

READY = """
LOCATION
browser.serve((request) => {
  if (request.route === "/api/range/ready/") return {body: {ready: true, max_sessions: 2, slot: {number: 1}}};
  if (request.route === "/api/sessions/") return {body: []};
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", name: "Board", public_url: "http://board.com", attacks: 9, benign: 6, objectives: 3,
                    foundations: FOUNDATIONS}]};
  }
  return {status: 404, body: {detail: "not served"}};
});
""".replace("FOUNDATIONS", FOUNDATIONS)

CATALOGUE = """
  await browser.wait(500);
  const hidden = (name) => browser.element(name).classList.contains('hidden');
  return {capacity: browser.text('capacity'), health: hidden('range-health'), canary: hidden('range-pipeline'),
          cards: browser.text('wargames')};
"""

@pytest.mark.parametrize("operator", [False, True], ids=["learner", "operator"])
def test_the_catalogue_shows_range_controls_only_in_the_operator_view(client, operator):
    setup = READY.replace("LOCATION", 'location.search = "?operator";' if operator else "")
    seen = open_page(client, "/", setup=setup, scenario=CATALOGUE)
    shown = seen["result"]

    assert seen["errors"] == []
    assert worded("main.lesson_number", 1) in shown["cards"], "foundations are called lessons"
    assert (shown["capacity"] == worded("main.capacity", 0, 2)) is operator
    assert shown["health"] is not operator and shown["canary"] is not operator, (
        "the alert ingest check and the network state are operator controls")
    assert (worded("main.counts", 9, 6, 3) in shown["cards"]) is operator

GATED = (
    "let open;\nconst gate = new Promise((resolve) => { open = resolve; });\n"
    + COURSE.replace(
        "browser.serve((request) => {",
        'browser.serve(async (request) => {\n'
        '  if (request.route === "/api/sessions/1/score/") await gate;',
        1,
    )
)

LAYOUT = """
  const hidden = (name) => browser.element(name).classList.contains('hidden');
  const shown = () => Object.fromEntries(
    ['loading', 'session-card', 'consoles', 'activity', 'scoreboard'].map((name) => [name, !hidden(name)]));
"""

def test_the_result_page_shows_the_course_and_verdict_at_once_and_placeholders_until_the_score_is_read(client):
    seen = open_page(client, "/session/1/", setup=GATED, scenario=LAYOUT + """
      for (let i = 0; i < 6; i += 1) await browser.settle();
      const waiting = {layout: shown(), course: browser.text('course-rows'), objectives: browser.text('objective-rows'),
                       judged: browser.text('judgement'), cases: browser.text('case-rows'), slow: !hidden('score-slow')};
      open();
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return {waiting, done: shown(), lost: browser.text('lost-count'), slow: !hidden('score-slow')};
    """)
    shown = seen["result"]
    waiting = shown["waiting"]

    assert seen["errors"] == []
    assert waiting["layout"] == {
        "loading": False, "session-card": True, "consoles": False, "activity": False, "scoreboard": True}, (
        "the closed session's header and summary are on screen while the score is on its way; no loading line stands alone")
    assert worded("lesson.map.title") in waiting["course"], "the course summary does not wait for the score"
    for part in ("objectives", "judged", "cases"):
        assert worded("session.loading.result") in waiting[part], "each table says what it is waiting for"
    assert waiting["slow"] is False
    assert shown["done"] == waiting["layout"]
    assert shown["lost"] == "1 / 1"
    assert shown["slow"] is False

def test_a_score_that_takes_longer_than_fifteen_seconds_says_so_and_can_be_asked_again(client):
    seen = open_page(client, "/session/1/", setup=GATED, scenario=LAYOUT + """
      for (let i = 0; i < 6; i += 1) await browser.settle();
      const asked = () => browser.requests.filter((r) => r.route === "/api/sessions/1/score/").length;
      await browser.wait(14000);
      const early = !hidden('score-slow');
      await browser.wait(2000);
      const late = {shown: !hidden('score-slow'), text: browser.text('score-slow-text'), button: browser.text('score-retry')};
      const before = asked();
      await browser.click('score-retry');
      const retried = {asked: asked() - before, shown: !hidden('score-slow')};
      open();
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return {early, late, retried, lost: browser.text('lost-count'), slow: !hidden('score-slow')};
    """)
    shown = seen["result"]

    assert seen["errors"] == []
    assert shown["early"] is False
    assert shown["late"]["shown"] and shown["late"]["text"] and shown["late"]["button"]
    assert shown["retried"] == {"asked": 1, "shown": False}
    assert shown["lost"] == "1 / 1" and shown["slow"] is False

LIVE = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", guidance: true, kind: "lesson", ready: true,
      lesson_id: "f1", defense: "full", lesson: {text: "lesson.map", steps: [{id: "entry"}, {id: "route"}]},
      started_at: "2026-10-18T09:00:00Z", ended_at: null, lessons: [{id: "f1", started_at: "2026-10-18T09:00:00Z"}],
      result: {objectives: {lost: 0, undetected: 0, total: 3}, scenario: null}}};
  }
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", name: "Board", public_url: "http://board.com", foundations: FOUNDATIONS}]};
  }
  if (request.route === "/api/sessions/1/cases/") {
    return {body: [
      {name: "board-normal-search", malicious: false, detected: false, meta: {seed: true}, started_at: "2026-10-18T09:00:05Z"},
      {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, meta: {}, started_at: "2026-10-18T09:05:00Z"},
    ]};
  }
  return {status: 404, body: {detail: "not served"}};
});
""".replace("FOUNDATIONS", FOUNDATIONS)

def test_an_opened_lesson_session_offers_one_console_button_and_its_step_and_no_activity_panel(client):
    seen = open_page(client, "/session/1/", setup=LIVE, scenario=LAYOUT + """
      return {layout: shown(), blue: browser.text('blue'), red: !hidden('red'), figures: browser.text('session-figures'),
              state: browser.text('session-state'), crumbs: browser.text('crumbs'), title: browser.text('session-title'),
              asked: browser.requests.filter((r) => r.route === "/api/sessions/1/cases/").length};
    """)
    shown = seen["result"]

    assert seen["errors"] == []
    assert shown["layout"] == {
        "loading": False, "session-card": True, "consoles": True, "activity": False, "scoreboard": False}, (
        "a lesson hides its automatic requests while open, so the activity panel would only ever be empty")
    assert (shown["blue"], shown["red"], shown["asked"]) == (worded("session.blue.title"), False, 0)
    assert shown["state"] == "", "a ready session needs no state label; only an opening one says so"
    assert worded("main.step", 1, 2) in shown["figures"], "the subtitle names the lesson; the counter does not repeat it"
    assert "903" not in shown["crumbs"] and worded("wargame.board.name") in shown["crumbs"], (
        "the trail names the wargame, not a session number")
    assert worded("common.session", 1) == shown["title"], "the session page itself keeps the number"

def test_a_session_that_cannot_be_read_says_so_instead_of_showing_an_empty_page(client):
    seen = open_page(client, "/session/1/", setup="""
      browser.serve((request) => ({status: 500, body: {detail: "busy"}}));
    """, scenario=LAYOUT + """
      const first = {layout: shown(), unread: browser.text('unread')};
      const before = browser.requests.filter((r) => r.route === "/api/sessions/1/").length;
      await browser.wait(6000);
      const after = browser.requests.filter((r) => r.route === "/api/sessions/1/").length;
      return {first, retried: after > before};
    """)
    shown = seen["result"]

    assert shown["first"]["layout"] == {
        "loading": False, "session-card": False, "consoles": False, "activity": False, "scoreboard": False}
    assert shown["first"]["unread"]
    assert shown["retried"], "a busy server is asked again"

COURSES = """[{id: "c1", title: "course.logs.title", lessons: ["f1", "f2", "f3"], scored: false},
              {id: "c2", title: "course.attack.title", lessons: ["f4", "f5", "f6"], scored: true}]"""
ATTACK_COURSE = COURSE.replace('{id: "f1", started_at: "2026-10-18T09:00:00Z"}', '{id: "f4", started_at: "2026-10-18T09:00:00Z"}').replace(
    '{id: "f1", steps: 2, passed: 2, skipped: 0, hints: 0}', '{id: "f4", steps: 1, passed: 1, skipped: 0, hints: 0}').replace(
    'lesson: "f1", step: null, seed: true', 'lesson: "f4", step: null, seed: true').replace(
    'foundations: [', f'courses: {COURSES}, foundations: [', 1)
LOGS_COURSE = COURSE.replace('{id: "f5", started_at: "2026-10-18T09:10:00Z"}', '{id: "f2", started_at: "2026-10-18T09:10:00Z"}').replace(
    '{id: "f6", started_at: "2026-10-18T09:25:00Z"}', '{id: "f3", started_at: "2026-10-18T09:25:00Z"}').replace(
    '{id: "f5", steps: 9, passed: 8, skipped: 1, hints: 0}', '{id: "f2", steps: 1, passed: 1, skipped: 0, hints: 0}').replace(
    '{id: "f6", steps: 2, passed: 2, skipped: 0, hints: 0}', '{id: "f3", steps: 1, passed: 1, skipped: 0, hints: 0}').replace(
    'foundations: [', f'courses: {COURSES}, foundations: [', 1)
SCORED = SHOWN.replace("restart: browser.text('restart')}", "restart: browser.text('restart'), "
                       "panels: !browser.element('score-panels').classList.contains('hidden'), "
                       "listed: !browser.element('score-cases').classList.contains('hidden'), "
                       "figures: browser.text('session-figures')}")

def test_a_course_s_result_numbers_its_lessons_as_the_catalogue_does_and_shows_a_score_only_for_a_scored_course(client):
    attack = open_page(client, "/session/1/", setup=ATTACK_COURSE, scenario=SCORED)
    logs = open_page(client, "/session/1/", setup=LOGS_COURSE, scenario=SCORED)
    shown, read = attack["result"], logs["result"]

    assert ATTACK_COURSE.count("courses: [") == 1 and LOGS_COURSE.count("courses: [") == 1
    assert attack["errors"] == [] and logs["errors"] == []
    assert worded("course.attack.title") in shown["line"]
    assert worded("session.run.step", 2, 4) in shown["cases"] and worded("session.run.step", 3, 2) in shown["cases"]
    assert shown["restart"] == worded("session.restart")
    assert (shown["panels"], shown["listed"]) == (True, True)
    assert (read["panels"], read["listed"]) == (False, False), (
        "the logs course only reads the range: no objective is at stake and no attack is sent, so it shows no score")
    assert worded("session.lost") not in read["figures"]

def test_one_case_sent_in_each_lesson_is_listed_per_lesson_in_the_table_and_not_restated_under_the_count(client):
    three = ATTACK_COURSE.replace('''        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, detections: 1, corroborated: false,
         lesson: "f5", step: "sqlmap", seed: false},''', '''        {name: "board-normal-search", malicious: false, detected: false, detections: 0, corroborated: null,
         lesson: "f5", step: null, seed: true},
        {name: "board-normal-search", malicious: false, detected: false, detections: 0, corroborated: null,
         lesson: "f6", step: null, seed: true},''')
    seen = open_page(client, "/session/1/", setup=three, scenario=SHOWN)

    assert three != ATTACK_COURSE and seen["errors"] == []
    assert all(worded("session.run.lesson", number) in seen["result"]["cases"] for number in (1, 2, 3))
    assert worded("score.benign", 3, 3) in seen["result"]["judged"]
    assert worded("case.board-normal-search") not in seen["result"]["judged"], (
        "requests that passed are counted above and listed in the table; the count does not restate them")

FINISHED_COURSES = READY.replace("LOCATION", "").replace(
    'if (request.route === "/api/sessions/") return {body: []};',
    'if (request.route === "/api/sessions/") return {body: request.query.state === "closed" ? CLOSED_ROWS : []};').replace(
    f"foundations: {FOUNDATIONS}}}]", f'foundations: {FOUNDATIONS}, courses: [{{id: "c1", title: "course.logs.title", lessons: ["f1", "f2", "f3"], scored: false}}, '
    '{id: "c2", title: "course.attack.title", lessons: ["f4", "f5", "f6"], scored: true}], scenarios: [{id: "1.1", title: "scenario.shift.title"}]}]')
CLOSED_ROWS = """const CLOSED_ROWS = [
  {id: 7, scenario: "board", kind: "lesson", lesson_id: "f3", started_at: "2026-10-18T09:00:00Z", ended_at: "2026-10-18T09:40:00Z",
   result: {objectives: {total: 3, lost: 0, undetected: 0}}},
  {id: 8, scenario: "board", kind: "lesson", lesson_id: "f6", started_at: "2026-10-18T10:00:00Z", ended_at: "2026-10-18T10:40:00Z",
   result: {objectives: {total: 3, lost: 0, undetected: 0}}}];
"""

def test_the_catalogue_names_a_lesson_session_by_its_course_and_claims_no_kept_objectives_for_a_course_without_a_score(client):
    seen = open_page(client, "/", setup=CLOSED_ROWS + FINISHED_COURSES, scenario="""
      await browser.wait(500);
      const rows = document.querySelectorAll('#finished tr').map((row) => row.querySelectorAll('td').map((cell) => cell.textContent.trim()));
      return {rows, grid: browser.element('wargames').className, cards: browser.text('wargames')};
    """)
    rows = {row[0]: row[1:3] for row in seen["result"]["rows"]}

    assert seen["errors"] == []
    assert rows[worded("common.session", 7)] == [worded("course.logs.title"), "—"], "course 1 has no score to keep"
    assert rows[worded("common.session", 8)] == [worded("course.attack.title"), worded("result.kept_all", 3)]
    assert "flex-col" in seen["result"]["grid"].split(), "targets stack in one column, so a short one leaves no empty column beside a long one"
    assert worded("scenario.shift.title") in seen["result"]["cards"]

SCENARIO_RESULT = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", kind: "scenario", course_scenario: "1.1", ready: true, lesson: {text: "scenario.shift", steps: []},
      started_at: "2026-10-18T09:00:00Z", ended_at: "2026-10-18T09:07:00Z", result: {objectives: {lost: 0, total: 0}, scenario: null}}};
  }
  if (request.route === "/api/wargames/") return {body: [{id: "board", name: "Board", public_url: "http://board.com", foundations: []}]};
  if (request.route === "/api/wargames/board/objectives/") return {body: []};
  if (request.route === "/api/sessions/1/score/") {
    return {body: {breaches: [], per_case: [], warnings: [], customers: {sent: 788, blocked: 14, blocked_actions: {}}}};
  }
  if (request.route === "/api/sessions/1/scenario/debrief/") {
    return {body: {overview: {verified: 0, steps: {passed: 0, total: 5}, help: {hints: 0}, fix: null},
      customers: {sent: 788, served: 774, blocked: 14, in_window: [], blocked_actions: {}},
      timeline: [{at: 150, case: "board-sqli-orderby-sqlmap", origin: "ru", state: "cancelled", in_window: false, leaked: []}],
      task_class: "judgement", triage: {right: 0, items: 14, first_try: 0}, evidence: [],
      change: {before: {paranoia: 2}, after: {paranoia: 2}, diff: []},
      cases: [{name: "board-sqli-orderby-sqlmap", before: null, after: null}], risk: [],
      at: {opened: "2026-10-18T09:00:00Z", verified: null}}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_scenario_result_says_only_what_happened_in_scenario_words_and_says_it_once(client):
    seen = open_page(client, "/session/1/", setup=SCENARIO_RESULT, scenario="""
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return {debrief: browser.text('debrief'), judged: browser.text('judgement'),
              sections: document.querySelectorAll('#debrief [data-debrief]').map((one) => one.dataset.debrief),
              cases: !browser.element('score-cases').classList.contains('hidden')};
    """)
    shown = seen["result"]

    assert seen["errors"] == []
    assert shown["sections"] == ["overview", "customers", "timeline", "triage", "change"], (
        "no empty evidence, before-and-after or risk heading")
    assert worded("scenario.debrief.from", worded("scenario.origin.ru")) in shown["debrief"]
    assert worded("lesson.debrief.change.none") in shown["debrief"]
    assert worded("scenario.debrief.overview", 0) not in shown["debrief"]
    assert shown["judged"] == worded("score.no_attacks_run"), (
        "customer requests are in the debrief once, not again beside the attacks")
    assert shown["cases"] is False

def test_a_lost_objective_row_in_the_catalogue_is_one_phrase_with_nothing_joined_to_it(client):
    lost = CLOSED_ROWS.replace("result: {objectives: {total: 3, lost: 0, undetected: 0}}}];",
                               "result: {objectives: {total: 3, lost: 3, undetected: 3}}}];")
    seen = open_page(client, "/", setup=lost + FINISHED_COURSES, scenario="""
      await browser.wait(500);
      return document.querySelectorAll('#finished tr').map((row) => row.querySelectorAll('td').map((cell) => cell.textContent.trim()));
    """)
    rows = {row[0]: row[1:3] for row in seen["result"]}

    assert seen["errors"] == []
    assert rows[worded("common.session", 8)] == [worded("course.attack.title"), worded("result.lost", 3, 3)]

def test_one_end_session_confirmation_is_said_the_same_on_the_session_page_and_in_the_console(client):
    from tests.test_lesson_console import RIGHT, answering, served, to

    page = open_page(client, "/session/1/", setup=CLOSED_ELSEWHERE, scenario="""
      for (let i = 0; i < 4; i += 1) await browser.settle();
      await browser.click('close');
      const asked = document.querySelector('#confirm');
      return {said: asked.querySelector('p').textContent.trim(), shown: !asked.classList.contains('hidden')};
    """)
    console = open_page(client, "/blue/1/", setup=served(next_lesson=None), scenario=f"""
      {to("db_ip")}
      {answering(RIGHT["db_ip"])}
      await browser.wait(2500);
      document.querySelector('#step-act [data-act="close"]').click();
      await browser.settle();
      const asked = document.querySelector('#step-act [data-act="confirm"]');
      return {{said: asked.querySelector('p').textContent.trim(), shown: !asked.classList.contains('hidden')}};
    """)

    assert page["errors"] == [] and console["errors"] == []
    assert page["result"] == console["result"] == {"said": worded("session.close.consequence"), "shown": True}

def test_starting_or_restarting_a_lesson_opens_its_console_not_a_page_holding_one_button(client):
    restart = open_page(client, "/session/1/", setup=COURSE, scenario="""
      await browser.click('restart');
      await browser.settle();
      return location.href;
    """)
    start = open_page(client, "/", setup=READY.replace("LOCATION", "").replace(
        'if (request.route === "/api/sessions/") return {body: []};',
        'if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 5}};\n'
        '  if (request.route === "/api/sessions/") return {body: []};'), scenario="""
      await browser.wait(500);
      await browser.click('[data-lesson-id="f1"]');
      await browser.settle();
      return location.href;
    """)

    assert restart["errors"] == [] and start["errors"] == []
    assert restart["result"] == "/blue/2/" and start["result"] == "/blue/5/"

CLOSED_ELSEWHERE = """
const range = {ended: null};
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", kind: "scenario", course_scenario: "1.1", ready: true, lesson: {text: "scenario.shift", steps: []},
      started_at: "2026-10-18T09:00:00Z", ended_at: range.ended,
      result: {objectives: {lost: 0, total: 0}, scenario: range.ended ? {passed: false, helped: []} : null}}};
  }
  if (request.route === "/api/sessions/1/close/") {
    range.ended = "2026-10-18T09:07:00Z";
    return {status: 409, body: {detail: "session 1 closed at 2026-10-18T09:07:00+00:00"}};
  }
  if (request.route === "/api/sessions/1/ingest/") return {body: {ingested: 0}};
  if (request.route === "/api/wargames/") return {body: [{id: "board", name: "Board", public_url: "http://board.com", foundations: []}]};
  if (request.route === "/api/wargames/board/objectives/") return {body: []};
  if (request.route === "/api/sessions/1/score/") return {body: {breaches: [], per_case: [], warnings: [], customers: {sent: 0, blocked: 0, blocked_actions: {}}}};
  if (request.route === "/api/sessions/1/scenario/debrief/") return {status: 409, body: {detail: "x"}};
  if (request.route === "/api/sessions/1/activity/") return {body: {events: []}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_ending_a_session_already_closed_says_it_is_closed_in_korean_and_hides_the_end_button(client):
    seen = open_page(client, "/session/1/", setup=CLOSED_ELSEWHERE, scenario="""
      for (let i = 0; i < 4; i += 1) await browser.settle();
      await browser.click('close');
      await browser.click('confirm-close');
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return {note: browser.text('closed'), close: browser.element('close').classList.contains('hidden'),
              verdict: browser.text('verdict')};
    """)
    shown = seen["result"]

    assert seen["errors"] == []
    assert shown["note"] == worded("session.close.done") and shown["close"] is True
    assert worded("scenario.verdict.failed", "1.1") in shown["verdict"] and "FAIL" not in shown["verdict"]

TWO_RUNS = SCENARIO_RESULT.replace("per_case: [], warnings: []", """per_case: [
      {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, detections: 20687, started_at: "2026-10-18T09:02:33Z"},
      {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, detections: 20687, started_at: "2026-10-18T09:13:06Z"}],
    warnings: []""")

def test_two_runs_of_one_scheduled_attack_are_told_apart_by_when_they_ran(client):
    seen = open_page(client, "/session/1/", setup=TWO_RUNS, scenario="""
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return document.querySelectorAll('#case-rows tr').map((row) => row.querySelector('td').textContent);
    """)

    assert seen["errors"] == []
    named = seen["result"]
    assert len(named) == 2 and named[0] != named[1], "two rows with one name read as one run counted twice"

RUNNING_PASSED = SCENARIO_RESULT.replace('ended_at: "2026-10-18T09:07:00Z", result: {objectives: {lost: 0, total: 0}, scenario: null}',
                                         'ended_at: null, result: {objectives: {lost: 0, total: 3}, scenario: {passed: true, fix: null, windows: 1, helped: []}}')

def test_an_open_scenario_that_passed_shows_its_result_beside_the_end_button(client):
    seen = open_page(client, "/session/1/", setup=RUNNING_PASSED, scenario="""
      for (let i = 0; i < 6; i += 1) await browser.settle();
      const hidden = (id) => browser.element(id).classList.contains('hidden');
      return {verdict: hidden('scoreboard') || hidden('verdict') ? "" : browser.text('verdict'), close: !hidden('close'),
              debrief: !hidden('debrief'), scores: !hidden('score-panels')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"verdict": worded("scenario.verdict.passed", "1.1"), "close": True, "debrief": True,
                              "scores": False}, "the page holding the end button said nothing about the pass"

DETECTION_RESULT = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", kind: "scenario", course_scenario: "3.3", ready: true, lesson: {text: "scenario.tamper", steps: []},
      started_at: "2026-10-18T09:00:00Z", ended_at: "2026-10-18T09:08:00Z", result: {objectives: {lost: 0, total: 0}, scenario: null}}};
  }
  if (request.route === "/api/wargames/") return {body: [{id: "board", name: "Board", public_url: "http://board.com", foundations: []}]};
  if (request.route === "/api/wargames/board/objectives/") return {body: []};
  if (request.route === "/api/sessions/1/score/") {
    return {body: {breaches: [], warnings: [], detected_by: "suricata",
      per_case: [{name: "board-sqli-orderby-sqlmap-tamper", malicious: true, detected: false, detections: 0, started_at: "2026-10-18T09:02:01Z"},
                 {name: "board-sqli-orderby-sqlmap-tamper", malicious: true, detected: true, detections: 14, started_at: "2026-10-18T09:06:10Z"}],
      customers: {sent: 870, alerted: 1, blocked: 0, blocked_actions: {},
                  alerted_requests: [{sent_at: "2026-10-18T09:03:00Z", action: "sort", method: "GET", path: "/?sort=-created_at"}]}}};
  }
  if (request.route === "/api/sessions/1/scenario/debrief/") {
    return {body: {overview: {verified: 1, steps: {passed: 0, total: 0}, help: {hints: 0}, fix: null},
      customers: {sent: 870, served: 870, blocked: 0, in_window: [0], blocked_actions: {}},
      timeline: [{at: 121, case: "board-sqli-orderby-sqlmap-tamper", origin: "ru", state: "fired", in_window: false, leaked: [], outcome: "held", detected: false},
                 {at: 370, case: "board-sqli-orderby-sqlmap-tamper", origin: "ru", state: "fired", in_window: true, leaked: [], outcome: "held", detected: true}],
      task_class: "detection", triage: {right: 0, items: 0, first_try: 0}, evidence: [],
      change: {before: {paranoia: 1}, after: {paranoia: 1}, diff: [], ids: []},
      cases: [{name: "board-sqli-orderby-sqlmap-tamper", before: "held", after: "held", alerted_before: false, alerted_after: true}],
      risk: [], at: {opened: "2026-10-18T09:00:00Z", verified: "2026-10-18T09:08:00Z"}}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def detection_result(client, scenario):
    seen = open_page(client, "/session/1/", setup=DETECTION_RESULT, scenario="for (let i = 0; i < 6; i += 1) await browser.settle();\n"
                     + scenario)
    assert seen["errors"] == []
    return seen["result"]

def local_clock(instant):
    from datetime import datetime

    return datetime.fromisoformat(instant).astimezone().strftime("%H:%M")

def test_a_detection_scenario_result_shows_the_customer_requests_beside_the_attacks(client):
    shown = detection_result(client, """
      return {judged: browser.text('judgement'), row: document.querySelector('#case-rows [data-customers]').textContent};
    """)

    assert worded("score.customers_alerted", 870, 869) in shown["judged"]
    assert worded("score.customer_alert", local_clock("2026-10-18T09:03:00+00:00"), "GET /?sort=-created_at") in shown["judged"]
    assert worded("score.customers_row", 870) in shown["row"] and worded("score.wrongly_blocked") in shown["row"]

def test_a_missed_attack_in_the_detection_summary_says_when_it_ran_so_a_later_caught_run_of_it_is_not_read_as_missed(client):
    judged = detection_result(client, "return browser.text('judgement');")
    missed = local_clock("2026-10-18T09:02:01+00:00")
    caught = local_clock("2026-10-18T09:06:10+00:00")
    label = worded("case.board-sqli-orderby-sqlmap-tamper")

    assert worded("score.no_alert", f"{missed} {label}") in judged
    assert worded("score.no_alert", f"{caught} {label}") not in judged
    assert "—" not in judged

def test_a_case_row_states_its_verdict_once_with_the_ids_alert_count_as_detail(client):
    shown = detection_result(client, """
      return {headers: document.querySelectorAll('#score-cases th').length, note: browser.text('score-counted-by'),
              cells: document.querySelectorAll('#case-rows tr').map((row) => row.querySelectorAll('td')[2].textContent.trim())};
    """)

    assert shown["headers"] == 3, "the alert count is no column of its own"
    assert shown["note"] == worded("score.counted_by.suricata")
    assert shown["cells"][:2] == [worded("score.missed"), f'{worded("score.caught")} {worded("score.alert_count", 14)}']

def test_a_scenario_result_without_steps_names_the_scenario_in_its_header(client):
    setup = DETECTION_RESULT.replace('lesson: {text: "scenario.tamper", steps: []},', "lesson: null,").replace(
        'public_url: "http://board.com", foundations: []}', 'public_url: "http://board.com", foundations: [], '
        'scenarios: [{id: "3.3", title: "scenario.tamper.title"}]}')
    seen = open_page(client, "/session/1/", setup=setup, scenario="return browser.text('session-line');")

    assert "lesson: null" in setup and seen["errors"] == []
    assert seen["result"].startswith(f'3.3 {worded("scenario.tamper.title")} · ')

def test_a_session_s_minutes_agree_with_the_start_and_end_times_it_shows(client):
    setup = DETECTION_RESULT.replace('started_at: "2026-10-18T09:00:00Z", ended_at: "2026-10-18T09:08:00Z"',
                                     'started_at: "2026-10-18T09:00:50Z", ended_at: "2026-10-18T09:03:11Z"')
    seen = open_page(client, "/session/1/", setup=setup, scenario="return browser.text('session-line');")

    assert setup != DETECTION_RESULT and seen["errors"] == []
    assert seen["result"].endswith(worded("session.span", local_clock("2026-10-18T09:00:50+00:00"),
                                          local_clock("2026-10-18T09:03:11+00:00"), 3))

def test_a_one_lesson_session_of_a_course_is_named_by_its_course_as_a_longer_one_is(client):
    setup = COURSE.replace('{id: "f5", started_at: "2026-10-18T09:10:00Z"},\n                {id: "f6", started_at: "2026-10-18T09:25:00Z"}', "").replace(
        'public_url: "http://board.com", foundations:',
        'public_url: "http://board.com", courses: [{id: "c2", title: "course.attack.title", lessons: ["f1", "f5", "f6"]}], foundations:')
    seen = open_page(client, "/session/1/", setup=setup, scenario="return browser.text('session-line');")

    assert "09:10:00Z" not in setup and "course.attack.title" in setup and seen["errors"] == []
    assert seen["result"].startswith(f'{worded("course.attack.title")} · ')

def test_a_scenario_without_objectives_shows_no_objectives_card(client):
    shown = detection_result(client, "return !browser.element('objectives-card').classList.contains('hidden');")

    assert shown is False

def test_the_timeline_and_the_case_table_tell_the_same_wall_clock_time(client):
    shown = detection_result(client, """
      return {timeline: document.querySelectorAll('#debrief [data-timeline]').map((one) => one.textContent.trim()),
              cases: browser.text('case-rows')};
    """)
    fired = local_clock("2026-10-18T09:02:01+00:00")

    assert shown["timeline"][0].startswith(fired) and fired in shown["cases"]
    assert "2:01" not in shown["timeline"][0]

def test_before_and_after_says_whether_the_attack_drew_an_alert(client):
    shown = detection_result(client, """
      const row = document.querySelector('#debrief [data-case]');
      return {before: row.querySelector('[data-before]').textContent, after: row.querySelector('[data-after]').textContent};
    """)

    assert worded("scenario.debrief.no_alert") in shown["before"] and worded("scenario.debrief.alerted") in shown["after"]

def test_a_lesson_result_shows_each_lesson_s_own_change_under_that_lesson(client):
    applied = COURSE.replace("result: {objectives: {lost: 1, undetected: 1, total: 1}, scenario: null}}};",
                             'result: {objectives: {lost: 1, undetected: 1, total: 1}, scenario: null}, changes: ['
                             '{lesson: "f1", ids: ["+alert http any any -> any any (sid:9100001;)"]}, {lesson: "f5", ids: []}, '
                             '{lesson: "f6", ids: [], before: {paranoia: 1}, after: {paranoia: 1}, diff: [\'-SecAction "id:10001"\']}]}};')
    seen = open_page(client, "/session/1/", setup=applied, scenario="""
      return {shown: !browser.element('lesson-change').classList.contains('hidden'), text: browser.text('lesson-change'),
              lessons: document.querySelectorAll('#lesson-change [data-change-lesson]').map((one) => one.textContent)};
    """)

    assert applied != COURSE and seen["errors"] == []
    assert seen["result"]["shown"] is True
    assert seen["result"]["lessons"] == [f'{worded("session.run.lesson", 1)} · {worded("lesson.map.title")}',
                                         f'{worded("session.run.lesson", 6)} · {worded("lesson.miss.title")}'], (
        "a lesson the learner changed nothing in is left out; each change sits under the lesson it was made in")
    assert all(part in seen["result"]["text"] for part in (worded("lesson.debrief.change.ids"), "sid:9100001",
                                                           worded("lesson.debrief.change.waf"), "id:10001"))
    assert worded("lesson.debrief.change.unread") not in seen["result"]["text"]

def test_an_attack_not_run_before_the_final_check_says_so_in_the_before_column(client):
    setup = DETECTION_RESULT.replace('before: "held", after: "held", alerted_before: false, alerted_after: true',
                                     'before: null, after: "held", alerted_before: null, alerted_after: true')
    seen = open_page(client, "/session/1/", setup=setup, scenario="""
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return document.querySelector('#debrief [data-case] [data-before]').textContent;
    """)

    assert setup != DETECTION_RESULT and seen["errors"] == []
    assert seen["result"] == worded("scenario.debrief.not_run"), "a dash reads as data that failed to load"

def test_evidence_cut_at_its_row_limit_says_how_many_more_alerts_there_are(client):
    rows = ", ".join('{signature: "SQLi sort", method: "GET", path: "/?sort=x", phase: "attack", '
                     'case: "board-sqli-orderby-sqlmap-tamper"}' for _ in range(20))
    setup = DETECTION_RESULT.replace("evidence: [],", f"evidence: [{rows}], evidence_total: 22,")
    seen = open_page(client, "/session/1/", setup=setup, scenario="""
      for (let i = 0; i < 6; i += 1) await browser.settle();
      return {rows: document.querySelectorAll('#debrief [data-evidence]').length,
              more: document.querySelector('#debrief [data-evidence-more]').textContent};
    """)

    assert setup != DETECTION_RESULT and seen["errors"] == []
    assert seen["result"] == {"rows": 20, "more": worded("scenario.debrief.evidence_more", 2)}

def test_a_scenario_result_s_breadcrumb_names_the_scenario_as_its_header_does(client):
    setup = DETECTION_RESULT.replace('public_url: "http://board.com", foundations: []}',
                                     'public_url: "http://board.com", foundations: [], '
                                     'scenarios: [{id: "3.3", title: "scenario.tamper.title"}]}')
    seen = open_page(client, "/session/1/", setup=setup, scenario="return browser.text('crumbs');")
    played = f'3.3 {worded("scenario.tamper.title")}'

    assert setup != DETECTION_RESULT and seen["errors"] == []
    assert seen["result"] == " / ".join([worded("crumb.home"), f'{worded("wargame.board.name")} · {played}',
                                         worded("crumb.result")])
