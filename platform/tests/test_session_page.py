import re

import pytest

from tests.browser import english, open_page

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
      course: [{id: "f5", steps: 9, passed: 8, skipped: 1}],
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
        {name: "board-normal-search", malicious: false, detected: false, detection_ids: [], corroborated: null,
         lesson: "f1", step: null, seed: true},
        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: true, detection_ids: ["d"], corroborated: false,
         lesson: "f5", step: "sqlmap", seed: false},
        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: false, detection_ids: [], corroborated: null,
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
    assert english("session.run.step", 5, 4) in shown["cases"] and english("session.run.step", 6, 2) in shown["cases"], (
        "the same sqlmap case ran in two lessons; each run says where it came from")
    assert english("session.run.lesson", 1) in shown["cases"]
    assert shown["lost"] == "1 / 1" and english("score.benign", 1, 1) in shown["judged"], (
        "both numbers stay on the page, side by side")
    assert english("lesson.map.title") in shown["course"] and english("lesson.miss.title") in shown["course"], (
        "after a course the page sums up every lesson taken, not only the last")
    assert english("session.course.steps", 9, 8) in shown["course"]
    assert english("session.course.span", 1, 6) in shown["line"]

def test_restarting_a_course_starts_its_first_lesson_with_that_lesson_s_defence(client):
    seen = open_page(client, "/session/1/", setup=COURSE, scenario="""
      const label = browser.text('restart');
      await browser.click('restart');
      return {label, posted: browser.requests.filter((r) => r.method === "POST" && r.route === "/api/sessions/")};
    """)

    assert seen["result"]["label"] == english("session.restart.course")
    assert [request["body"] for request in seen["result"]["posted"]] == [
        {"scenario": "board", "guidance": True, "lesson": "f1", "defense": "full"}], (
        "restarting from F6 with F6's posture would open F1 on the overbroad WAF exclusion")

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
    assert english("main.lesson_number", 1) in shown["cards"], "foundations are called lessons"
    assert (shown["capacity"] == english("main.capacity", 0, 2)) is operator
    assert shown["health"] is not operator and shown["canary"] is not operator, (
        "the alert ingest check and the network state are operator controls")
    assert (english("main.counts", 9, 6, 3) in shown["cards"]) is operator
