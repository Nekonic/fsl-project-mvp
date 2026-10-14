import json

import pytest

import wargames
from api import views
from tests.browser import english, open_page
from tests.test_scenario_console import serving, status

pytestmark = pytest.mark.django_db

def shown(lesson_id):
    taught = wargames.lesson("board", lesson_id=lesson_id)
    return {key: value for key, value in taught.items() if key != "steps"} | {
        "steps": [views._shown_step(None, step) for step in taught.get("steps", [])],
    }

RULES = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
localStorage.setItem('fsl-lesson-step-1', 'STEP_AT');
localStorage.setItem('fsl-scenario-briefed-1', 'true');
const rules = {text: "alert http any any -> any any (msg:\\"base\\"; sid:9000002;)\\n", version: "r1",
               validated: [], applied: [], checked: [], invalid: false};
"""

ROUTES = '''if (request.route === "/api/rules/") return {body: {content: rules.text, version: rules.version}};
  if (request.route === "/api/rules/validate/") {
    rules.validated.push(request.body);
    if (!rules.invalid) return {body: {ok: true, output: "", errors: []}};
    return {status: 400, body: {ok: false, output: "Info: x\\nError: detect-parse: unknown rule keyword 'contnet'.",
                                errors: ["Error: detect-parse: unknown rule keyword 'contnet'."]}};
  }
  if (request.route === "/api/rules/apply/") {
    rules.applied.push(request.body);
    rules.text = request.body.content;
    rules.version = "r2";
    return {body: {id: 1, content: request.body.content}};
  }
  if (request.route.startsWith("/api/sessions/1/lesson/steps/")) {
    const id = request.route.split("/")[6];
    if (request.route.endsWith("/check/")) rules.checked.push(id);
    return {body: {passed: false, reason: null, hint: 0, hints: [], progress: {}}};
  }
  if (request.route === "/api/sessions/1/ingest/")'''

def worked(scenario_id, step_id):
    lesson = shown(scenario_id)
    card = wargames.scenario_card(wargames.scenario_run(scenario_id))
    at = [step["id"] for step in lesson["steps"]].index(step_id) + 1
    return RULES.replace("STEP_AT", str(at)) + serving(status(card, id=scenario_id, cards=[]), lesson=lesson).replace(
        'if (request.route === "/api/sessions/1/ingest/")', ROUTES)

def test_a_worked_detection_scenario_edits_the_sensor_rules_validates_shows_suricata_s_error_and_applies_on_the_loaded_version(client):
    seen = open_page(client, "/blue/1/", setup=worked("3.1", "fix"), scenario="""
      await browser.click('[data-pane="rules"]');
      const loaded = document.getElementById('lesson-rules-text').value;
      rules.invalid = true;
      await browser.click('lesson-rules-apply');
      const refused = {status: browser.text('lesson-rules-status'), errors: browser.text('lesson-rules-errors')};
      rules.invalid = false;
      await browser.force('lesson-rules-text', rules.text + 'alert http any any -> any any (msg:"SQL"; sid:9000101;)\\n');
      await browser.click('lesson-rules-apply');
      return {loaded, refused, applied: rules.applied, status: browser.text('lesson-rules-status'),
              shown: !document.getElementById('lesson-rules').classList.contains('hidden'),
              title: browser.text('coach-pop-title'), checked: rules.checked};
    """)

    assert seen["errors"] == []
    result = seen["result"]
    assert result["shown"], "a detection scenario edits the sensor rules in the rules pane"
    assert result["title"] == english("scenario.fixrule.label.fix")
    assert result["loaded"].startswith('alert http any any -> any any (msg:"base"')
    assert result["refused"] == {"status": english("lesson.rules.invalid"),
                                 "errors": "Error: detect-parse: unknown rule keyword 'contnet'."}
    assert len(result["applied"]) == 1, "a refused file is never applied"
    assert result["applied"][0]["base"] == "r1" and result["applied"][0]["session"] == "1"
    assert "sid:9000101;" in result["applied"][0]["content"]
    assert result["status"] == english("lesson.rules.applied")
    assert "fix" in result["checked"], "applying runs the step that waits for the rule"

FOUNDATION = """
localStorage.setItem('fsl-lesson-landed-1', 'true');
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: true, hints: [], progress: {}, ended_at: null,
                   discover: "/kibana/app/discover#/", waf_box: "fsl-1-waf", waf_rules: "/etc/modsecurity.d", lesson: LESSON_JSON}};
  }
  if (request.route.startsWith("/api/sessions/1/lesson/steps/")) return {body: {hint: 0, hints: [], progress: {}}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_foundation_says_in_its_goal_that_it_is_done_when_its_steps_are_and_offers_no_verify(client):
    seen = open_page(client, "/blue/1/", setup=FOUNDATION.replace("LESSON_JSON", json.dumps(shown("f1"))), scenario="""
      return {done: browser.text('lesson-done'), verify: document.getElementById('lesson-verify-section') === null};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"done": english("lesson.goal.done.steps"), "verify": True}
