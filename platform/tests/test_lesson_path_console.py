import json

import pytest

import wargames
from api import views
from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

def shown(lesson_id):
    taught = wargames.lesson("board", lesson_id=lesson_id)
    return {key: value for key, value in taught.items() if key not in views.SERVER_ONLY} | {
        "steps": [views._shown_step(None, dict(step, query=None)) | ({"discover": "/kibana/app/discover#/?narrowed"}
                                                                      if step.get("query") else {})
                  for step in taught.get("steps", [])],
        "verifies": views._verifies(taught),
    }

SESSION = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
const range = {rules: "alert http any any -> any any (msg:\\"base\\"; sid:9000002;)\\n", version: "r1", waf: {paranoia: 4, exclusions: [{rule_id: 920273, target: "ARGS:q", path: "/search/"}]},
               validated: [], applied: [], puts: [], checked: [], invalid: false};
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: true, mode: "guided", hints: [], progress: {}, ended_at: null, start: null,
                   discover: "/kibana/app/discover#/", waf_box: "fsl-1-waf", waf_rules: "/etc/modsecurity.d", lesson: LESSON_JSON}};
  }
  if (request.route === "/api/rules/") return {body: {content: range.rules, version: range.version}};
  if (request.route === "/api/rules/validate/") {
    range.validated.push(request.body);
    if (!range.invalid) return {body: {ok: true, output: "", errors: []}};
    return {status: 400, body: {ok: false, output: "Info: x\\nError: detect-parse: unknown rule keyword 'contnet'.",
                                errors: ["Error: detect-parse: unknown rule keyword 'contnet'."]}};
  }
  if (request.route === "/api/rules/apply/") {
    range.applied.push(request.body);
    range.rules = request.body.content;
    range.version = "r2";
    return {body: {id: 1, content: request.body.content}};
  }
  if (request.route === "/api/sessions/1/waf/" && request.method === "GET") return {body: range.waf};
  if (request.route === "/api/sessions/1/waf/" && request.method === "PUT") {
    range.puts.push(request.body);
    range.waf = request.body;
    return {body: request.body};
  }
  if (request.route.startsWith("/api/sessions/1/lesson/steps/")) {
    const id = request.route.split("/")[6];
    if (request.route.endsWith("/check/")) {
      range.checked.push(id);
      if (id === "stock") {
        return {body: {passed: true, reason: null, hint: 0, hints: [], progress: {}, detected: {
          name: "board-sqli-orderby-sqlmap", outcome: "detected", verdict: "TP",
          signatures: ["FSL SQLi attempt - sort is not a column name"], discover: "/kibana/app/discover#/?sensed"}}};
      }
      return {body: {passed: true, reason: null, hint: 0, hints: [], progress: {}}};
    }
    return {body: {hint: 0, hints: [], progress: {}}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def session(lesson_id):
    return SESSION.replace("LESSON_JSON", json.dumps(shown(lesson_id)))

def to(step_id):
    return f"""
      document.querySelectorAll('#lesson-step-list [data-step]').forEach((button) => {{
        if (button.textContent.includes({json.dumps(english(f"lesson.ids.label.{step_id}"))})) button.click();
      }});
      await browser.settle();
    """

def test_an_ids_lesson_edits_the_sensor_rules_validates_shows_suricata_s_error_and_applies_on_the_loaded_version(client):
    seen = open_page(client, "/blue/1/", setup=session("ids-signature"), scenario=to("write") + """
      const loaded = document.getElementById('lesson-rules-text').value;
      range.invalid = true;
      await browser.click('lesson-rules-apply');
      const refused = {status: browser.text('lesson-rules-status'), errors: browser.text('lesson-rules-errors')};
      range.invalid = false;
      await browser.force('lesson-rules-text', range.rules + 'alert http any any -> any any (msg:"SQL"; sid:9000101;)\\n');
      await browser.click('lesson-rules-apply');
      return {loaded, refused, applied: range.applied, status: browser.text('lesson-rules-status'),
              shown: !document.getElementById('lesson-rules').classList.contains('hidden'),
              level: document.getElementById('lesson-level').classList.contains('hidden'),
              checked: range.checked};
    """)

    assert seen["errors"] == []
    result = seen["result"]
    assert result["shown"] and result["level"], "the lesson's controls are the rule editor only"
    assert result["loaded"].startswith('alert http any any -> any any (msg:"base"')
    assert result["refused"] == {"status": english("lesson.rules.invalid"),
                                 "errors": "Error: detect-parse: unknown rule keyword 'contnet'."}
    assert len(result["applied"]) == 1, "a refused file is never applied"
    assert result["applied"][0]["base"] == "r1" and result["applied"][0]["session"] == "1"
    assert "sid:9000101;" in result["applied"][0]["content"]
    assert result["status"] == english("lesson.rules.applied")
    assert "write" in result["checked"], "applying runs the step that waits for the rule"

def test_a_detect_step_sends_its_case_and_shows_the_alert_and_its_verdict(client):
    seen = open_page(client, "/blue/1/", setup=session("ids-signature"), scenario=f"""
      {to("stock")}
      await browser.click('[data-act="detect"]');
      return {{button: browser.text('[data-act="detect"]'), verdict: browser.text('[data-verdict]'),
               alerts: browser.text('[data-alerts]'), checked: range.checked}};
    """)

    assert seen["errors"] == []
    result = seen["result"]
    assert result["button"].startswith(english("lesson.detect.check").split("{0}")[0])
    assert result["verdict"] == "TP"
    assert "FSL SQLi attempt - sort is not a column name" in result["alerts"]
    assert "stock" in result["checked"]

def test_the_ids_goal_says_done_means_alerts_on_attacks_and_none_on_ordinary_requests(client):
    seen = open_page(client, "/blue/1/", setup=session("ids-signature"), scenario="""
      return {done: browser.text('lesson-done'),
              verify: document.getElementById('lesson-verify-section').classList.contains('hidden')};
    """)

    assert english("lesson.goal.done.detected") in seen["result"]["done"]
    assert english("lesson.goal.done.quiet") in seen["result"]["done"]
    assert seen["result"]["verify"] is False

def test_a_lesson_judged_by_its_steps_hides_verify_and_says_so_in_its_goal(client):
    seen = open_page(client, "/blue/1/", setup=session("console-tour"), scenario="""
      return {done: browser.text('lesson-done'),
              verify: document.getElementById('lesson-verify-section').classList.contains('hidden')};
    """)

    assert seen["result"] == {"done": english("lesson.goal.done.steps"), "verify": True}

def test_the_level_control_puts_the_chosen_level_and_keeps_the_exclusions_in_force(client):
    seen = open_page(client, "/blue/1/", setup=session("choose-the-level"), scenario="""
      const read = document.getElementById('lesson-level-pick').value;
      await browser.choose('lesson-level-pick', '2');
      await browser.click('lesson-level-apply');
      return {read, puts: range.puts, status: browser.text('lesson-level-status'), checked: range.checked};
    """)

    assert seen["errors"] == []
    assert seen["result"]["read"] == "4"
    assert seen["result"]["puts"] == [{"paranoia": 2, "exclusions": [
        {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}]}]
    assert seen["result"]["status"] == english("lesson.level.applied").replace("{0}", "2")

CATALOGUE = """
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", name: "Board", description: "", cases: 1, lesson: true, lessons: [
      {id: "assessment", order: 7, title: "lesson.exam.title", goal: "lesson.exam.summary", minutes: 40, level: "hard",
       defense: "minimal", prerequisites: [], steps: 0, mode: "self"}]}]};
  }
  if (request.route === "/api/sessions/" && request.method === "POST") return {status: 201, body: {id: 9}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_lesson_with_no_steps_offers_practice_and_the_wargame_but_no_guided_rung(client):
    seen = open_page(client, "/", setup=CATALOGUE, scenario="""
      return [...document.querySelectorAll('[data-lesson-card="assessment"] [data-mode]')].map((b) => b.dataset.mode);
    """)

    assert seen["errors"] == []
    assert seen["result"] == ["self"]
