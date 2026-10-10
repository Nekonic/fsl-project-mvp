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
        paranoia: browser.element('lesson-paranoia').value,
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
    assert shown["result"]["paranoia"] == "4", "the panel shows the paranoia level the WAF runs"
    assert shown["result"]["frame"] == "/kibana/", "Kibana stays beside the lesson"
    assert plain["result"]["hidden"] is True
    assert "/api/sessions/1/waf/" not in plain["result"]["routes"]

def test_applying_the_tuning_puts_the_level_and_the_exclusions_to_the_api(client):
    seen = open_page(client, "/blue/1/", setup=guided(True), scenario="""
      await browser.force('lesson-paranoia', '4');
      await browser.force('lesson-exclusions', '920273 ARGS:q /search/\\n942100');
      await browser.click('lesson-save');
      return browser.requests.filter((r) => r.method === 'PUT').map((r) => [r.route, r.body]);
    """)

    assert seen["result"] == [["/api/sessions/1/waf/", {"paranoia": 4, "exclusions": [
        {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"},
        {"rule_id": 942100, "target": "", "path": ""},
    ]}]]

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
