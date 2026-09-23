from json import dumps as js

import pytest

from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/"]

@pytest.mark.parametrize("path", PAGES)
def test_every_console_page_runs_its_script_without_an_error(client, path):
    seen = open_page(client, path)

    assert seen["errors"] == [], (
        f"{path} threw while loading against a platform that answers 404 to "
        f"everything; a page that throws stops drawing where it threw"
    )

BLUE_RANGE = """
const SCORE = {
  tp: 1, fp: 0, fn: 0, tn: 1, precision: 1.0, recall: 1.0, f1: 1.0,
  false_positive_rate: 0.0, benign_cases: 1, unattributed: 0, warnings: [],
  per_case: [], breaches: [],
  objectives: {
    objectives: 0, difficulty_total: 0, detected: 0, undetected: 0,
    detected_difficulty: 0, undetected_difficulty: 0, coverage: 1.0,
    damage: 0.0, false_positives: 0,
  },
};
const COMMAND = {at: "2026-09-23T16:25:54Z", case_id: null, text: "sqlmap -u http://shop.com"};
const ANSWERS = {
  "/api/sessions/1/ingest/": {ingested: 0, skipped: 0},
  "/api/sessions/1/detections/": [],
  "/api/sessions/1/top/": {sources: [], destinations: [], signatures: [], paths: []},
  "/api/sessions/1/map/": {points: [], unlocated: 0},
  "/api/sessions/1/score/": SCORE,
  "/api/sessions/1/commands/": {commands: [COMMAND]},
  "/api/sessions/1/cases/": [],
  "/api/rules/": {content: ""},
  "/api/rules/suppressions/": {suppressions: [], restored: []},
};
const healthy = (request) => request.route in ANSWERS
  ? {body: ANSWERS[request.route]}
  : {status: 404, body: {detail: "not served"}};
const failing = (route, detail, when = () => true) => (request) =>
  request.route === route && when(request) ? {status: 503, body: {detail}} : healthy(request);
browser.serve(healthy);
"""

INDICATOR = """
const indicator = () => ({
  label: browser.text("live-label"),
  dot: browser.element("live-dot").className,
  title: browser.element("live-toggle").title,
});
"""

def test_the_live_indicator_says_not_reachable_while_the_platform_does_not_answer(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + INDICATOR + "browser.serve(browser.offline);",
        scenario="""
          const down = indicator();
          browser.serve(healthy);
          await browser.poll();
          return {down, back: indicator()};
        """,
    )["result"]
    down, back = seen["down"], seen["back"]

    assert down["label"] == english("blue.live.unreachable"), (
        "every poll failed and the console still showed a pulsing Live"
    )
    assert "bg-rose-500" in down["dot"] and "bg-emerald-400" not in down["dot"]
    assert back["label"] == english("blue.live.on")
    assert "bg-emerald-400" in back["dot"] and back["title"] == ""

def test_the_live_indicator_carries_the_reason_the_platform_gave(client):
    reason = "Elasticsearch did not answer at http://elasticsearch:9200"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + INDICATOR
        + f"browser.serve(failing('/api/sessions/1/ingest/', {js(reason)}));",
        scenario="return indicator();",
    )["result"]

    assert seen["label"] == english("blue.live.unreachable"), (
        "the read answered but nothing new was ingested, so the alerts on "
        "screen stopped moving while the console said Live"
    )
    assert seen["title"] == reason

def test_a_failed_ingest_keeps_the_last_truncation_warning(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + """
          ANSWERS["/api/sessions/1/ingest/"] = {
            ingested: 0, skipped: 0, truncated: {read: 10000, total: 26000},
          };
        """,
        scenario="""
          const banner = () => ({
            shown: !browser.element("truncated").classList.contains("hidden"),
            text: browser.text("truncated"),
          });
          const read = banner();
          browser.serve(failing("/api/sessions/1/ingest/", "Elasticsearch did not answer"));
          await browser.poll();
          return {read, failed: banner()};
        """,
    )["result"]
    warning = english("blue.truncated", 10000, 26000)

    assert seen["read"] == {"shown": True, "text": warning}
    assert seen["failed"] == {"shown": True, "text": warning}, (
        "an ingest that failed hid the warning that the score is computed on "
        "part of the evidence, although nothing more of it had been read"
    )

def test_a_strategy_that_cannot_be_scored_says_so_instead_of_keeping_its_last_numbers(client):
    reason = "the window strategy found no session window"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE,
        scenario=f"""
          await browser.click('[data-tab="score"]');
          const scored = browser.text("comparison");
          browser.serve(failing("/api/sessions/1/score/", {js(reason)},
                                (request) => request.query.correlation === "window"));
          await browser.click('[data-tab="score"]');
          return {{scored, failed: browser.text("comparison")}};
        """,
    )
    counts = english("blue.score.comparison.counts", 1, 0, 0, 1)

    assert seen["result"]["scored"].count(counts) == 2
    assert seen["errors"] == [], "the comparison threw instead of reporting the failure"
    assert english("blue.score.comparison.error", "window", reason) in seen["result"]["failed"]
    assert seen["result"]["failed"].count(counts) == 1, (
        "the strategy that failed kept showing the numbers of the last one that did not"
    )

def test_an_operator_log_that_cannot_be_read_says_so_instead_of_keeping_its_last_rows(client):
    reason = "fsl-kali is not running"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE,
        scenario=f"""
          await browser.click('[data-tab="score"]');
          const read = browser.text("operator-log");
          browser.serve(failing("/api/sessions/1/commands/", {js(reason)}));
          await browser.click('[data-tab="score"]');
          return {{read, failed: browser.text("operator-log")}};
        """,
    )

    assert "sqlmap -u http://shop.com" in seen["result"]["read"]
    assert seen["errors"] == [], "the operator log threw instead of reporting the failure"
    assert seen["result"]["failed"] == english("blue.score.operator.unavailable", reason), (
        "the log that could not be read kept showing the commands of the last one that could"
    )
