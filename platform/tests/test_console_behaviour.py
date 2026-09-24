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

ALERTS = r"""
const alert = (id, fields = {}) => ({
  id, detection_id: `es-${id}:0`, source: "suricata", signature: "FSL SQLi attempt - URI",
  severity: 3, timestamp: "2026-09-23T16:25:54Z", src_ip: "5.188.10.3", marker: null,
  dest_ip: "10.10.0.5", dest_port: 80, method: "GET", path: "/rest/products/search",
  ...fields,
});
let DETECTIONS = [];
const answerAlerts = (request) => {
  if (request.route === "/api/sessions/1/detections/") {
    return {body: DETECTIONS.filter((d) => d.id > Number(request.query.after || 0))};
  }
  const detail = /^\/api\/detections\/(\d+)\/$/.exec(request.route);
  if (detail) {
    const found = DETECTIONS.find((d) => d.id === Number(detail[1]));
    return {body: {...found, raw: {}, session: 1}};
  }
  return healthy(request);
};
browser.serve(answerAlerts);
const table = (id) => Object.fromEntries(
  browser.element(id).innerHTML.split("<tr ").slice(1).map((row) => [
    /data-id="([^"]*)"/.exec(row)[1],
    row.split(/<td\b/).slice(1).map((cell) =>
      cell.slice(cell.indexOf(">") + 1).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()),
  ]));
const column = (index) => Object.fromEntries(
  Object.entries(table("rows")).map(([id, cells]) => [id, cells[index]]));
const caseColumn = () => column(10);
const tiles = (id) => Object.fromEntries(
  browser.element(id).innerHTML.split('<div class="bg-slate-900/60').slice(1).map((tile) =>
    [...tile.matchAll(/<div class="[^"]*">([^<]*)<\/div>/g)].slice(0, 2).map((m) => m[1].trim())));
const onlyUnattributed = async () => {
  browser.element("only-orphans").checked = true;
  await browser.force("only-orphans", "on");
};
"""

SQLI_CASE = "6f1d2c3b-5a4e-4f60-9b8a-7c6d5e4f3a2b"

PLACED = f"""
DETECTIONS = [
  alert(1),
  alert(2, {{marker: {js(SQLI_CASE)}}}),
  alert(3),
];
ANSWERS["/api/sessions/1/score/"] = {{
  ...SCORE, tp: 2, tn: 0, benign_cases: 0, unattributed: 1,
  per_case: [
    {{case_id: "0b9e8d7c-window", name: "manual probe", malicious: true, detected: true,
      verdict: "TP", detection_ids: ["es-1:0"], expect: "", corroborated: null}},
    {{case_id: {js(SQLI_CASE)}, name: "sqli-union-user-table", malicious: true,
      detected: true, verdict: "TP", detection_ids: ["es-2:0"], expect: "SQL",
      corroborated: true}},
  ],
}};
"""

def test_the_unattributed_tile_counts_what_the_score_places_in_no_case(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + """
          DETECTIONS = [
            alert(1, {marker: "0d5a1c2e-3b4f-4a6d-8e9f-a0b1c2d3e4f5"}),
            alert(2, {marker: "9b7f3e41-2c5d-4e6f-8a9b-c0d1e2f3a4b5"}),
            alert(3),
          ];
          ANSWERS["/api/sessions/1/score/"] = {
            ...SCORE, tp: 0, tn: 0, benign_cases: 0, unattributed: 3, per_case: [],
          };
        """,
        scenario="""
          const dashboard = browser.text("kpi-orphan");
          await browser.click('[data-tab="score"]');
          return {dashboard, score: tiles("totals")};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["score"][english("blue.score.tile.unattributed")] == "3"
    assert seen["result"]["dashboard"] == "3", (
        "two alerts carried a case marker that belongs to no case in the session, "
        "and the Dashboard counted only the one without a marker while the Score "
        "tab counted all three as belonging to no case"
    )

def test_an_alert_a_window_case_placed_is_not_shown_as_unattributed(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACED,
        scenario="""
          const tile = browser.text("kpi-orphan");
          const cases = caseColumn();
          await onlyUnattributed();
          return {tile, cases, filtered: Object.keys(table("rows")), shown: browser.text("shown")};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["tile"] == "1", (
        "an alert with no marker that a window case claimed was counted as unattributed"
    )
    assert seen["result"]["cases"] == {
        "1": "manual probe",
        "2": "sqli-union-user-table",
        "3": english("blue.unattributed"),
    }
    assert seen["result"]["filtered"] == ["3"]
    assert seen["result"]["shown"] == english("blue.alerts.count.filtered", 1, 3)

def test_a_case_recorded_after_its_alerts_arrived_takes_them_out_of_the_unattributed(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACED + """
          const placedLater = ANSWERS["/api/sessions/1/score/"];
          ANSWERS["/api/sessions/1/score/"] = {
            ...placedLater, unattributed: 2, per_case: placedLater.per_case.slice(1),
          };
        """,
        scenario="""
          const before = {tile: browser.text("kpi-orphan"), cases: caseColumn()};
          ANSWERS["/api/sessions/1/score/"] = placedLater;
          await browser.poll();
          return {before, after: {tile: browser.text("kpi-orphan"), cases: caseColumn()}};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"]["tile"] == "2"
    assert seen["result"]["after"] == {
        "tile": "1",
        "cases": {
            "1": "manual probe",
            "2": "sqli-union-user-table",
            "3": english("blue.unattributed"),
        },
    }, (
        "the window case was recorded at Stop, after its alerts had arrived, and "
        "the console kept showing them unattributed because no new alert came in"
    )

def test_the_drawer_names_the_case_the_score_placed_the_alert_in(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACED,
        scenario="""
          const meta = [];
          for (const id of [1, 2, 3]) {
            await openDrawer(id);
            meta.push(browser.text("drawer-meta"));
          }
          return meta;
        """,
    )
    at, source = "2026-09-23T16:25:54Z", "5.188.10.3"

    assert seen["errors"] == []
    assert seen["result"] == [
        english("blue.drawer.meta.attributed", "suricata", at, source, "manual probe"),
        english("blue.drawer.meta.attributed", "suricata", at, source, "sqli-union-user-table"),
        english("blue.drawer.meta.unattributed", "suricata", at, source),
    ]

def test_an_unreadable_score_leaves_the_unattributed_count_unknown(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACED + """
          browser.serve((request) => request.route === "/api/sessions/1/score/"
            ? {status: 500, body: {detail: "the catalogue could not be read"}}
            : answerAlerts(request));
        """,
        scenario="""
          return {tile: browser.text("kpi-orphan"), cases: caseColumn()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == {"tile": "-", "cases": {"1": "-", "2": "-", "3": "-"}}, (
        "the score could not be read and the console fell back to counting "
        "alerts without a marker, which is not what belongs to no case"
    )

SEVERITIES = [
    ("suricata", 1, "high"),
    ("suricata", 2, "medium"),
    ("suricata", 3, "low"),
    ("suricata", 4, "info"),
    ("suricata", None, "info"),
    ("modsecurity", 0, "high"),
    ("modsecurity", 2, "high"),
    ("modsecurity", 3, "medium"),
    ("modsecurity", 4, "medium"),
    ("modsecurity", 5, "low"),
    ("modsecurity", 7, "low"),
    ("modsecurity", None, "info"),
]

def test_each_engine_s_severity_is_read_on_its_own_scale(client):
    detections = ", ".join(
        f"alert({index}, {{source: {js(source)}, severity: {js(severity)}}})"
        for index, (source, severity, _) in enumerate(SEVERITIES, start=1)
    )
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + f"DETECTIONS = [{detections}];",
        scenario="return column(1);",
    )

    assert seen["errors"] == []
    assert seen["result"] == {
        str(index): english(f"blue.alerts.severity.{level}")
        for index, (_, _, level) in enumerate(SEVERITIES, start=1)
    }, (
        "ModSecurity reports the syslog scale, where CRS marks an attack 2 "
        "(CRITICAL) and its blocking rule 949110 carries 0, and the console read "
        "it on Suricata's 1 to 3 scale: a WAF block showed as Info and a SQL "
        "injection as Medium"
    )

@pytest.mark.parametrize("per_bar", [1, 10])
def test_evenly_spaced_alerts_fill_every_bar_of_the_histogram_alike(client, per_bar):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + f"""
          const START = Date.parse("2026-09-23T16:00:00Z");
          const COUNT = 48 * {per_bar};
          DETECTIONS = Array.from({{length: COUNT}}, (_, i) =>
            alert(i + 1, {{timestamp: new Date(START + i * 60000).toISOString()}}));
        """,
        scenario="""
          return [...browser.element("histogram").innerHTML.matchAll(/title="([^"]*)"/g)]
            .map((m) => m[1]);
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == [english("blue.histogram.bar_title", per_bar)] * 48, (
        "the newest bar held only the alerts at the single latest timestamp, "
        "while the other 47 shared everything else"
    )

def test_the_false_positives_are_shown_once_with_the_benign_cases_they_are_out_of(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + """
          ANSWERS["/api/sessions/1/score/"] = {
            ...SCORE, tp: 4, fn: 2, fp: 3, tn: 5, benign_cases: 8,
          };
        """,
        scenario=r"""
          await browser.click('[data-tab="score"]');
          return browser.element("totals").innerHTML.split('<div class="bg-slate-900/60').slice(1)
            .map((tile) => [...tile.matchAll(/<div class="[^"]*">([^<]*)<\/div>/g)]
              .map((m) => m[1].trim()));
        """,
    )
    showing_fp = [tile for tile in seen["result"] if "3" in tile[1]]

    assert seen["errors"] == []
    assert showing_fp == [
        [english("blue.score.tile.fp"), "3", english("blue.score.tile.fp_of_benign", 8)],
    ], (
        "the grid showed the false positives on two tiles, FP and False "
        "positives, and only one of them said how many benign cases they are out of"
    )

@pytest.mark.parametrize("counts, shown", [
    ({"tp": 1, "fp": 0, "fn": 0, "tn": 1}, ("1.00", "1.00", "1.00")),
    ({"tp": 0, "fp": 0, "fn": 2, "tn": 1}, ("-", "0.00", "0.00")),
    ({"tp": 0, "fp": 1, "fn": 0, "tn": 0}, ("0.00", "-", "-")),
    ({"tp": 0, "fp": 0, "fn": 0, "tn": 1}, ("-", "-", "-")),
], ids=["all-defined", "nothing-flagged", "nothing-malicious", "only-benign"])
def test_a_ratio_with_nothing_to_divide_by_is_shown_as_undefined(client, counts, shown):
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    ratios = {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
    }
    total = ratios["precision"] + ratios["recall"]
    ratios["f1"] = 2 * ratios["precision"] * ratios["recall"] / total if total else 0.0
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + f"""
          ANSWERS["/api/sessions/1/score/"] = {{
            ...SCORE, ...{js(counts)}, ...{js(ratios)},
            benign_cases: {counts["fp"] + counts["tn"]},
          }};
        """,
        scenario="""
          await browser.click('[data-tab="score"]');
          return {tiles: tiles("totals"), comparison: browser.text("comparison")};
        """,
    )
    precision, recall, _ = shown
    tiles = seen["result"]["tiles"]

    assert seen["errors"] == []
    assert (
        tiles[english("blue.score.tile.precision")],
        tiles[english("blue.score.tile.recall")],
        tiles[english("blue.score.tile.f1")],
    ) == shown, (
        "the API reports 0.0 for a ratio whose denominator is zero, and the "
        "console showed it as 0.00, a score the defence did not earn or lose"
    )
    assert seen["result"]["comparison"].count(
        english("blue.score.comparison.rates", precision, recall)) == 2

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

ASLEEP = """
let now = Date.now();
Date.now = () => now;
const sleep = (ms) => { now += ms; };
const HOUR = 60 * 60 * 1000;
const shown = async (state) => {
  document.visibilityState = state;
  document.dispatchEvent({type: "visibilitychange"});
  await browser.settle();
};
const wake = async () => {
  document.visibilityState = "visible";
  document.dispatchEvent({type: "visibilitychange"});
  window.dispatchEvent({type: "online"});
  await browser.settle();
};
const count = (method, route) =>
  browser.requests.filter((r) => r.method === method && r.route === route).length;
"""

def test_a_blue_console_woken_from_sleep_catches_up_once(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + INDICATOR + ASLEEP,
        scenario="""
          const ingests = () => count("POST", "/api/sessions/1/ingest/");
          browser.serve(browser.offline);
          await browser.poll();
          const asleep = indicator();
          sleep(HOUR);
          const before = ingests();
          await shown("hidden");
          const hidden = ingests() - before;
          browser.serve(healthy);
          await wake();
          const woke = {polls: ingests() - before, indicator: indicator()};
          await wake();
          const again = ingests() - before;
          await browser.click("live-toggle");
          sleep(HOUR);
          await wake();
          return {asleep, hidden, woke, again, paused: ingests() - before};
        """,
    )["result"]

    assert seen["asleep"]["label"] == english("blue.live.unreachable")
    assert seen["hidden"] == 0, "a page going out of sight was polled for it"
    assert seen["woke"]["polls"] == 1, (
        "the page came back after an hour and waited for its timer, which a "
        "browser holds back for a page it did not show, before it looked again"
    )
    assert seen["woke"]["indicator"]["label"] == english("blue.live.on")
    assert seen["again"] == 1, (
        "coming back into view and back online together polled once for each"
    )
    assert seen["paused"] == 1, "a paused console polled because it came back into view"

HELD_INGEST = """
let release;
const answered = new Promise((resolve) => { release = resolve; });
browser.serve((request) => request.route === "/api/sessions/1/ingest/"
  ? answered.then(() => healthy(request))
  : healthy(request));
const ingests = () =>
  browser.requests.filter((request) => request.route === "/api/sessions/1/ingest/").length;
"""

def test_a_slow_ingest_is_not_overtaken_by_the_next_poll(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + HELD_INGEST,
        scenario="""
          for (let interval = 0; interval < 4; interval += 1) await browser.poll();
          const during = ingests();
          release();
          await browser.settle();
          await browser.poll();
          return {during, after: ingests()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        "four poll intervals passed while the first ingest was still running, and "
        "each one started another ingest of the same session beside it"
    )
    assert seen["result"]["after"] == 2, "polling stopped once the slow ingest finished"

HELD_READ = """
let release;
const answered = new Promise((resolve) => { release = resolve; });
const holding = (route) => (request) => request.route === route
  ? answered.then(() => answerAlerts(request))
  : answerAlerts(request);
const asked = (route) => browser.requests.filter((request) => request.route === route).length;
let arriving = 100;
const arrive = () => { DETECTIONS.push(alert(arriving)); arriving += 1; };
"""

@pytest.mark.parametrize("route, tab, restoring", [
    ("/api/sessions/1/map/", "dashboard", False),
    ("/api/sessions/1/commands/", "score", False),
    ("/api/sessions/1/cases/", "score", False),
    ("/api/rules/suppressions/", "rules", True),
])
def test_what_a_poll_draws_finishes_before_the_next_poll(client, route, tab, restoring):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + HELD_READ + (
            'ANSWERS["/api/sessions/1/ingest/"] = '
            '{ingested: 0, skipped: 0, restored: [{sid: 2100001, ok: true, detail: null}]};'
            if restoring else ""
        ),
        scenario=f"""
          await browser.click('[data-tab="{tab}"]');
          browser.serve(holding({js(route)}));
          const before = asked({js(route)});
          for (let interval = 0; interval < 4; interval += 1) {{
            arrive();
            await browser.poll();
          }}
          const during = asked({js(route)}) - before;
          release();
          await browser.settle();
          arrive();
          await browser.poll();
          return {{during, after: asked({js(route)}) - before}};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        f"{route} did not answer, and every poll on the {tab} tab asked for it "
        f"again beside the one still open: the poll waited for its own reads but "
        f"not for what it started drawing"
    )
    assert seen["result"]["after"] == 2, "polling stopped once the slow read finished"

def test_two_draws_of_the_score_at_once_show_each_warning_once(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + """
          ANSWERS["/api/sessions/1/score/"] = {
            ...SCORE, warnings: [["score.warning.truncated", 10000, 26000]],
          };
          let release;
          const answered = new Promise((resolve) => { release = resolve; });
          const holdingScore = (request) =>
            request.route === "/api/sessions/1/score/" && !request.query.correlation
              ? answered.then(() => healthy(request))
              : healthy(request);
        """,
        scenario="""
          browser.serve(holdingScore);
          await browser.click('[data-tab="score"]');
          await browser.click('[data-tab="score"]');
          release();
          await browser.settle();
          return browser.element("warnings").innerHTML.split("bg-amber-950").length - 1;
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == 1, (
        "two draws of the score overlapped, as a poll and a click on the tab can, "
        "and both cleared the warnings before either added its own, so each warning "
        f"showed {seen['result']} times"
    )

def test_resuming_the_live_view_during_a_slow_ingest_does_not_start_another(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + HELD_INGEST,
        scenario="""
          await browser.click("live-toggle");
          await browser.click("live-toggle");
          const during = ingests();
          release();
          await browser.settle();
          await browser.poll();
          return {during, after: ingests(), label: browser.text("live-label")};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        "pausing and resuming the live view started a second ingest while the "
        "first was still running"
    )
    assert seen["result"]["after"] == 2, "polling stopped once the slow ingest finished"
    assert seen["result"]["label"] == english("blue.live.on")

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
    assert english("blue.score.comparison.error", reason) in seen["result"]["failed"]
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

RULE = 'alert http any any -> any any (msg:"sqli"; sid:2100001; rev:1;)'
CONFLICT = "the rule file changed since it was loaded"

RULES_RANGE = f"""
const RULE = {js(RULE)};
const LIVE_RULES = {{content: RULE, version: "a1"}};
const SILENCED_RULES = {{content: `# ${{RULE}}`, version: "b2"}};
const SUPPRESSION = {{
  id: 1, sid: 2100001, reason: "noisy", created_at: "2026-09-23T16:25:54Z",
  expires_at: "2026-09-23T16:55:54Z", restored_at: null,
}};
ANSWERS["/api/rules/"] = LIVE_RULES;
const ROUTES = {{
  "GET /api/detections/7/": () => ({{
    body: {{
      id: 7, signature: "sqli", source: "suricata", timestamp: "2026-09-23T16:25:54Z",
      src_ip: "5.188.10.3", marker: null, raw: {{alert: {{signature_id: 2100001}}}},
    }},
  }}),
  "POST /api/rules/suppressions/": () => {{
    ANSWERS["/api/rules/"] = SILENCED_RULES;
    ANSWERS["/api/rules/suppressions/"] = {{suppressions: [SUPPRESSION], restored: []}};
    return {{status: 201, body: SUPPRESSION}};
  }},
  "POST /api/rules/suppressions/1/restore/": () => {{
    ANSWERS["/api/rules/"] = LIVE_RULES;
    ANSWERS["/api/rules/suppressions/"] = {{suppressions: [], restored: []}};
    return {{body: {{...SUPPRESSION, restored_at: "2026-09-23T16:30:00Z"}}}};
  }},
  "POST /api/rules/apply/": (request) => {{
    if (request.body.base !== ANSWERS["/api/rules/"].version) {{
      return {{status: 409, body: {{detail: {js(CONFLICT)}}}}};
    }}
    applied += 1;
    ANSWERS["/api/rules/"] = {{content: request.body.content, version: `applied-${{applied}}`}};
    return {{body: {{id: applied, content: request.body.content}}}};
  }},
}};
let applied = 0;
const applies = () => browser.requests
  .filter((request) => request.method === "POST" && request.route === "/api/rules/apply/")
  .map((request) => request.body);
const routed = (request) => {{
  const route = ROUTES[`${{request.method}} ${{request.route}}`];
  return route ? route(request) : healthy(request);
}};
browser.serve(routed);
"""

def test_suppressing_from_the_drawer_reloads_the_rules_editor(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE,
        scenario="""
          const before = browser.element("editor").value;
          await openDrawer(7);
          await browser.click("suppress");
          return {before, after: browser.element("editor").value};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"] == RULE
    assert seen["result"]["after"] == f"# {RULE}", (
        "the editor kept the rule file from before the suppression, so the next "
        "Apply would write the suppressed rule back while the list still showed "
        "it suppressed"
    )

def test_restoring_a_suppression_reloads_the_rules_editor(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE,
        scenario="""
          await openDrawer(7);
          await browser.click("suppress");
          const suppressed = browser.element("editor").value;
          await restoreSuppression(1);
          return {suppressed, restored: browser.element("editor").value};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["suppressed"] == f"# {RULE}"
    assert seen["result"]["restored"] == RULE, (
        "the editor kept the suppressed rule file after the rule was restored"
    )

def test_a_suppression_the_ingest_lifted_reloads_the_editor_and_the_list(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE + """
          ANSWERS["/api/rules/"] = SILENCED_RULES;
          ANSWERS["/api/rules/suppressions/"] = {suppressions: [SUPPRESSION], restored: []};
        """,
        scenario="""
          const rules = () => browser.requests.filter((request) => request.method === "GET"
            && ["/api/rules/", "/api/rules/suppressions/"].includes(request.route)).length;
          const shown = () => ({
            editor: browser.element("editor").value, list: browser.text("suppressions"),
          });
          const before = shown();
          const read = rules();
          await browser.poll();
          const quiet = rules() - read;
          ANSWERS["/api/sessions/1/ingest/"] = {
            ingested: 0, skipped: 0, restored: [{sid: 2100001, ok: true, detail: null}],
          };
          ANSWERS["/api/rules/"] = LIVE_RULES;
          ANSWERS["/api/rules/suppressions/"] = {suppressions: [], restored: []};
          await browser.poll();
          const after = shown();
          await browser.click("apply");
          return {before, quiet, after, base: applies()[0].base};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"]["editor"] == f"# {RULE}"
    assert "2100001" in seen["result"]["before"]["list"]
    assert seen["result"]["quiet"] == 0, (
        "a tick that lifted nothing re-read the rule file and would overwrite "
        "whatever was being typed in the editor"
    )
    assert seen["result"]["after"] == {
        "editor": RULE, "list": english("blue.rules.suppression.empty"),
    }, (
        "the ingest lifted an expired suppression and the console kept showing "
        "the rule suppressed, in the list and in the editor an Apply would write back"
    )
    assert seen["result"]["base"] == "a1"

def test_a_lift_that_failed_leaves_the_editor_alone_and_says_why_once(client):
    reason = "could not restore sid 2100001: reload failed, rolled back to the previous rule set"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE + f"""
          const FAILED = [{{sid: 2100001, ok: false, detail: {js(reason)}}}];
          ANSWERS["/api/rules/"] = SILENCED_RULES;
          ANSWERS["/api/rules/suppressions/"] = {{suppressions: [SUPPRESSION], restored: FAILED}};
          ANSWERS["/api/sessions/1/ingest/"] = {{ingested: 0, skipped: 0, restored: FAILED}};
          ROUTES["POST /api/rules/validate/"] = () => ({{body: {{ok: true, output: "valid"}}}});
          const reads = () => browser.requests.filter(
            (request) => request.method === "GET" && request.route === "/api/rules/").length;
        """,
        scenario="""
          await browser.click('[data-tab="rules"]');
          const said = browser.text("output");
          const before = reads();
          await browser.force("editor", "# my half-written fix");
          await browser.poll();
          const typed = browser.element("editor").value;
          await browser.click("validate");
          await browser.poll();
          await browser.poll();
          await renderSuppressions();
          await browser.settle();
          return {
            said, typed, reads: reads() - before,
            editor: browser.element("editor").value, output: browser.text("output"),
          };
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["said"] == english("blue.rules.lift_failed", 2100001, reason), (
        "an expired suppression could not be lifted and the console never said why"
    )
    assert seen["result"]["typed"] == "# my half-written fix", (
        "a poll whose lift failed restored nothing and still replaced the editor, "
        "so the operator lost what they were typing every few seconds"
    )
    assert seen["result"]["reads"] == 0
    assert seen["result"]["editor"] == "# my half-written fix"
    assert seen["result"]["output"] == "valid", (
        "the same failed lift was reported again on a later poll, over what the "
        "operator had asked for since"
    )

def test_a_rule_whose_lift_went_through_is_reported_again_when_a_later_lift_fails(client):
    reason = "could not restore sid 2100001: reload failed, rolled back to the previous rule set"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE + f"""
          const lifting = (ok) => ({{
            ingested: 0, skipped: 0, restored: [{{sid: 2100001, ok, detail: ok ? null : {js(reason)}}}],
          }});
          ROUTES["POST /api/rules/validate/"] = () => ({{body: {{ok: true, output: "valid"}}}});
        """,
        scenario="""
          ANSWERS["/api/sessions/1/ingest/"] = lifting(false);
          await browser.poll();
          await browser.click("validate");
          ANSWERS["/api/sessions/1/ingest/"] = lifting(true);
          await browser.poll();
          ANSWERS["/api/sessions/1/ingest/"] = lifting(false);
          await browser.poll();
          return browser.text("output");
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == english("blue.rules.lift_failed", 2100001, reason), (
        "sid 2100001 was lifted, silenced again, and its second lift failed "
        "without a word because the first failure had already been reported"
    )

def test_apply_names_the_version_of_the_rules_the_editor_was_filled_from(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE,
        scenario="""
          await browser.click("apply");
          await browser.click("apply");
          await openDrawer(7);
          await browser.click("suppress");
          await browser.click("apply");
          return {applies: applies(), said: browser.text("output")};
        """,
    )

    assert seen["errors"] == []
    assert [body.get("base") for body in seen["result"]["applies"]] == [
        "a1", "applied-1", "b2",
    ], (
        "Apply did not name the version it was loaded from, or kept naming the "
        "one from before its own apply or a suppression"
    )
    assert seen["result"]["applies"][-1]["content"] == f"# {RULE}"
    assert seen["result"]["said"] == english("blue.rules.applied")

def test_apply_over_a_rule_file_that_changed_since_it_was_loaded_says_so_and_reloads(client):
    theirs = 'drop http any any -> any any (msg:"theirs"; sid:2100002; rev:1;)'
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE,
        scenario=f"""
          ANSWERS["/api/rules/"] = {{content: {js(theirs)}, version: "z9"}};
          await browser.force("editor", "mine");
          await browser.click("apply");
          const refused = {{
            said: browser.text("output"),
            style: browser.element("output").className,
            editor: browser.element("editor").value,
          }};
          await browser.click("apply");
          return {{refused, applies: applies(), said: browser.text("output")}};
        """,
    )
    refused = seen["result"]["refused"]

    assert seen["errors"] == []
    assert refused["said"] == english("blue.rules.apply_failed", CONFLICT), (
        "the platform refused an Apply over a rule file that had changed and the "
        "console did not say why"
    )
    assert "text-rose-300" in refused["style"]
    assert refused["editor"] == theirs, (
        "the refused Apply left the editor on the rules it was loaded from, so "
        "the next Apply would be refused again or overwrite the change"
    )
    assert [body.get("base") for body in seen["result"]["applies"]] == ["a1", "z9"]
    assert seen["result"]["said"] == english("blue.rules.applied")

def test_an_editor_that_never_read_the_rules_cannot_apply_over_them(client):
    reason = "the sensor did not answer"
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + RULES_RANGE + f"""
          browser.serve((request) => request.method === "GET" && request.route === "/api/rules/"
            ? {{status: 503, body: {{detail: {js(reason)}}}}}
            : routed(request));
        """,
        scenario="""
          const unread = {editor: browser.element("editor").value, said: browser.text("output")};
          await browser.force("editor", "mine");
          browser.serve(routed);
          await browser.click("apply");
          return {unread, applies: applies(), editor: browser.element("editor").value};
        """,
    )
    unread = seen["result"]["unread"]
    [apply] = seen["result"]["applies"]

    assert seen["errors"] == []
    assert unread["editor"] == ""
    assert unread["said"] == english("blue.rules.load_failed", reason), (
        "the rules could not be read and the editor stood empty with nothing to "
        "say so, which reads as a sensor with no rules"
    )
    assert isinstance(apply.get("base"), str), (
        "Apply from an editor that never held the rules named no version, which "
        "asks the platform to replace the whole file without checking it"
    )
    assert seen["result"]["editor"] == RULE, (
        "the platform refused the Apply and the editor was not filled from the "
        "rules it now could read"
    )

RED_RANGE = """
const ORIGINS = [
  {id: "edge", network: "fsl_edge", label: "Moscow, Russia", subnet: "5.188.10.0/24",
   source_ip: "5.188.10.3", direct_ip: "5.188.10.2", address: "5.188.10.4",
   target_url: "http://5.188.10.4", default: true},
  {id: "edge-br", network: "fsl_edge-br", label: "Sao Paulo, Brazil",
   subnet: "177.54.144.0/24", source_ip: "177.54.144.2", direct_ip: "",
   address: "177.54.144.3", target_url: "http://177.54.144.3", default: false},
];
const chosen = (id) => ORIGINS.find((o) => o.id === id) || ORIGINS.find((o) => o.default);
const box = (origin) => ({
  container: "fsl-kali", source_ip: origin.source_ip, direct_ip: origin.direct_ip,
  origin: origin.id, origin_label: origin.label, target_url: origin.target_url,
  public_url: "http://shop.com", terminal_url: "http://localhost:7681",
});
const ANSWERS = {
  "GET /api/origins/": () => ({origins: ORIGINS}),
  "GET /api/attacker/": (request) => box(chosen(request.query.origin)),
  "POST /api/attacker/origin/": (request) => {
    const origin = chosen(request.body.origin);
    return {origin: origin.id, source_ip: origin.source_ip};
  },
  "POST /api/attacker/label/": () => ({ok: true}),
  "GET /api/sessions/1/": () => ({id: 1, scenario: "juice-shop"}),
  "GET /api/wargames/": () => [{id: "juice-shop", covers: [], uncovered: []}],
  "GET /api/wargames/juice-shop/cases/": () => [],
  "GET /api/wargames/juice-shop/objectives/": () => [],
  "GET /api/sessions/1/objectives/": () => [],
  "POST /api/sessions/1/objectives/": () => ({achieved: 0}),
  "POST /api/sessions/1/cases/": (request) => request.body,
};
const healthy = (request) => {
  const answer = ANSWERS[`${request.method} ${request.route}`];
  return answer ? {body: answer(request)} : {status: 404, body: {detail: "not served"}};
};
const CONTROLS = ["window-name", "window-malicious", "window-route", "origin"];
const disabled = () =>
  Object.fromEntries(CONTROLS.map((id) => [id, browser.element(id).disabled]));
browser.serve(healthy);
"""

UNLOCKED = {control: False for control in ("window-name", "window-malicious", "window-route", "origin")}
LOCKED = {control: True for control in UNLOCKED}

def test_nothing_that_decides_the_recorded_address_can_be_changed_while_recording(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE,
        scenario="""
          const before = disabled();
          await browser.click("window-toggle");
          const recording = disabled();
          const moved = [];
          for (const [id, value] of [["window-name", "renamed"],
                                     ["window-route", "direct"], ["origin", "edge-br"]]) {
            if (await browser.choose(id, value)) moved.push(id);
          }
          await browser.click("window-toggle");
          return {before, recording, moved, after: disabled()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"] == UNLOCKED
    assert seen["result"]["recording"] == LOCKED, (
        "the origin, route, name and disposition stayed live while recording, so "
        "the case could be stored against an address that never sent the traffic"
    )
    assert seen["result"]["moved"] == []
    assert seen["result"]["after"] == UNLOCKED

def test_a_window_is_recorded_against_the_address_it_was_started_from(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE,
        scenario="""
          await browser.choose("window-route", "direct");
          await browser.click("window-toggle");
          const shown = browser.text("window-status");
          await browser.force("origin", "edge-br");
          await browser.click("window-toggle");
          const posted = browser.requests.filter(
            (r) => r.method === "POST" && r.route === "/api/sessions/1/cases/");
          return {shown, posted: posted.map((r) => r.body)};
        """,
    )
    [case] = seen["result"]["posted"]

    assert seen["errors"] == []
    assert seen["result"]["shown"] == english("red.window.status.recording", "5.188.10.2")
    assert case["correlation"] == "window"
    assert case["source_ip"] == "5.188.10.2", (
        "the window was started from the attacker's direct address on edge and "
        "recorded against whatever origin and route were selected at Stop; window "
        "correlation matches alerts by this address, so its alerts went unmatched"
    )
    assert case["meta"] == {"origin": "edge", "route": "direct"}

@pytest.mark.parametrize("answer, said", [
    ("({status: 404, body: {}})", ("red.error.no_session",)),
    ("({status: 503, body: {detail: 'the database is locked'}})",
     ("red.error.session", "the database is locked")),
    ("browser.offline()", ("red.error.session", "TypeError: Failed to fetch")),
], ids=["missing", "refused", "unreachable"])
def test_a_session_that_could_not_be_read_is_not_said_to_be_missing(client, answer, said):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          browser.serve((request) => request.method === "GET" && request.route === "/api/sessions/1/"
            ? {answer}
            : healthy(request));
        """,
        scenario='return browser.text("attacks");',
    )

    assert seen["errors"] == []
    assert seen["result"] == english(*said), (
        "the page told the operator the session does not exist, and to start "
        "another, when the platform had only failed to answer for it"
    )

def test_a_window_that_could_not_start_leaves_its_controls_usable(client):
    reason = "fsl-proxy is not running"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          browser.serve((request) => request.route === "/api/attacker/label/"
            ? {{status: 503, body: {{detail: {js(reason)}}}}}
            : healthy(request));
        """,
        scenario="""
          await browser.click("window-toggle");
          return {controls: disabled(), status: browser.text("window-status")};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["status"] == english("red.window.status.marker_failed", reason)
    assert seen["result"]["controls"] == UNLOCKED, (
        "a window that never started left its controls locked"
    )

def test_a_window_whose_marker_could_not_be_cleared_keeps_recording(client):
    reason = "the proxy could not write /label/active: Read-only file system"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          const refusingToClear = (request) =>
            request.route === "/api/attacker/label/" && request.body.case_id === null
              ? {{status: 503, body: {{detail: {js(reason)}}}}}
              : healthy(request);
          const recorded = () => browser.requests.filter(
            (r) => r.method === "POST" && r.route === "/api/sessions/1/cases/").length;
          const state = () => ({{
            toggle: browser.text("window-toggle"),
            status: browser.text("window-status"),
            controls: disabled(),
            recorded: recorded(),
          }});
        """,
        scenario="""
          await browser.click("window-toggle");
          browser.serve(refusingToClear);
          await browser.click("window-toggle");
          const refused = state();
          browser.serve(healthy);
          await browser.click("window-toggle");
          return {refused, retried: state()};
        """,
    )
    refused, retried = seen["result"]["refused"], seen["result"]["retried"]

    assert seen["errors"] == []
    assert refused["status"] == english("red.window.status.clear_failed", reason), (
        "the proxy kept stamping the case after Stop and the window did not say so"
    )
    assert refused["toggle"] == english("red.window.stop")
    assert refused["controls"] == LOCKED
    assert refused["recorded"] == 0, (
        "the case was recorded as ended while the proxy was still stamping its "
        "marker into the terminal's traffic"
    )
    assert retried["toggle"] == english("red.window.start")
    assert retried["controls"] == UNLOCKED
    assert retried["recorded"] == 1

def test_an_origin_the_proxy_did_not_take_puts_the_select_back(client):
    reason = "the proxy could not write /label/origin: Read-only file system"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          const refusingOrigin = (request) =>
            request.method === "POST" && request.route === "/api/attacker/origin/"
              ? {{status: 503, body: {{detail: {js(reason)}}}}}
              : healthy(request);
        """,
        scenario="""
          const before = browser.element("origin").value;
          browser.serve(refusingOrigin);
          await browser.choose("origin", "edge-br");
          const refused = {
            origin: browser.element("origin").value,
            status: browser.text("window-status"),
            proxied: browser.text("box-proxied"),
            toggle: browser.element("window-toggle").disabled,
          };
          browser.serve(healthy);
          await browser.click("window-toggle");
          await browser.click("window-toggle");
          const posted = browser.requests.filter(
            (r) => r.method === "POST" && r.route === "/api/sessions/1/cases/");
          return {before, refused, posted: posted.map((r) => r.body)};
        """,
    )
    refused = seen["result"]["refused"]
    [case] = seen["result"]["posted"]

    assert seen["errors"] == []
    assert seen["result"]["before"] == "edge"
    assert refused["status"] == english("red.window.status.origin_failed", reason)
    assert refused["origin"] == "edge", (
        "the proxy refused the move to edge-br and the select still showed edge-br, "
        "so the operator believed the terminal left from Sao Paulo while it still "
        "left from Moscow"
    )
    assert refused["proxied"] == "5.188.10.3"
    assert refused["toggle"] is False
    assert case["source_ip"] == "5.188.10.3"
    assert case["meta"]["origin"] == "edge"

def test_a_first_origin_the_proxy_did_not_take_leaves_no_window_to_start(client):
    reason = "the proxy could not write /label/origin: Read-only file system"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          browser.serve((request) =>
            request.method === "POST" && request.route === "/api/attacker/origin/"
              ? {{status: 503, body: {{detail: {js(reason)}}}}}
              : healthy(request));
        """,
        scenario="""
          await browser.click("window-toggle");
          return {
            status: browser.text("window-status"),
            toggle: browser.element("window-toggle").disabled,
            labelled: browser.requests.filter((r) => r.route === "/api/attacker/label/").length,
          };
        """,
    )

    assert seen["errors"] == [], (
        "Start was pressed on a window that never learned where the terminal "
        "leaves from"
    )
    assert seen["result"]["status"] == english("red.window.status.origin_failed", reason)
    assert seen["result"]["toggle"] is True
    assert seen["result"]["labelled"] == 0

@pytest.mark.parametrize("method, route", [
    pytest.param("POST", "/api/attacker/origin/", id="origin-refused"),
    pytest.param("GET", "/api/attacker/", id="box-unreadable"),
])
def test_a_window_can_start_once_an_origin_goes_through_after_a_failed_one(client, method, route):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          let failures = 1;
          browser.serve((request) => {{
            if (request.method === {js(method)} && request.route === {js(route)} && failures) {{
              failures -= 1;
              return {{status: 503, body: {{detail: "the proxy did not answer in time"}}}};
            }}
            return healthy(request);
          }});
        """,
        scenario="""
          const atLoad = browser.element("window-toggle").disabled;
          await browser.choose("origin", "edge-br");
          const moved = {
            toggle: browser.element("window-toggle").disabled,
            status: browser.text("window-status"),
          };
          await browser.click("window-toggle");
          await browser.click("window-toggle");
          const recorded = browser.requests.filter(
            (r) => r.method === "POST" && r.route === "/api/sessions/1/cases/").map((r) => r.body);
          return {atLoad, moved, recorded};
        """,
    )
    moved = seen["result"]["moved"]

    assert seen["errors"] == []
    assert seen["result"]["atLoad"] is True
    assert moved["status"] == english("red.window.status.will_record", "177.54.144.2")
    assert moved["toggle"] is False, (
        "the proxy took the origin and the window said which address it would "
        "record, and Start stayed disabled until the page was reloaded"
    )
    [case] = seen["result"]["recorded"]
    assert case["source_ip"] == "177.54.144.2"
    assert case["meta"]["origin"] == "edge-br"

OVERLAPPING = """
ORIGINS.push({id: "edge-hk", network: "fsl_edge-hk", label: "Kwai Chung, Hong Kong",
  subnet: "103.152.220.0/24", source_ip: "103.152.220.2", direct_ip: "",
  address: "103.152.220.3", target_url: "http://103.152.220.3", default: false});
const held = [];
const holding = (method, route) => (request) =>
  request.method === method && request.route === route
    ? new Promise((resolve) => held.push({request, resolve}))
    : healthy(request);
const shown = () => ({
  select: browser.element("origin").value,
  proxied: browser.text("box-proxied"),
  toggle: browser.element("window-toggle").disabled,
});
const recordWindow = async () => {
  await browser.click("window-toggle");
  await browser.click("window-toggle");
  return browser.requests.filter(
    (r) => r.method === "POST" && r.route === "/api/sessions/1/cases/").map((r) => r.body);
};
const moves = () => browser.requests.filter(
  (r) => r.method === "POST" && r.route === "/api/attacker/origin/").map((r) => r.body.origin);
"""

def test_an_origin_refused_while_another_was_moving_leaves_the_window_on_the_one_taken(client):
    reason = "the proxy could not write /label/origin: Read-only file system"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + OVERLAPPING + f"""
          const refused = () => ({{status: 503, body: {{detail: {js(reason)}}}}});
        """,
        scenario="""
          browser.serve(holding("POST", "/api/attacker/origin/"));
          await browser.choose("origin", "edge-br");
          await browser.choose("origin", "edge-hk");
          const first = held.shift();
          first.resolve(healthy(first.request));
          await browser.settle();
          const second = held.shift();
          second.resolve(refused());
          await browser.settle();
          browser.serve(healthy);
          const after = shown();
          return {moves: moves(), after, status: browser.text("window-status"),
                  recorded: await recordWindow()};
        """,
    )
    after = seen["result"]["after"]
    [case] = seen["result"]["recorded"]

    assert seen["errors"] == []
    assert seen["result"]["moves"] == ["edge", "edge-br", "edge-hk"]
    assert seen["result"]["status"] == english("red.window.status.origin_failed", reason)
    assert after == {"select": "edge-br", "proxied": "177.54.144.2", "toggle": False}, (
        "the proxy took Sao Paulo and refused Hong Kong, and the select was put "
        "back on Hong Kong, the origin it had just refused"
    )
    assert case["source_ip"] == "177.54.144.2"
    assert case["meta"]["origin"] == "edge-br"

def test_a_window_is_recorded_from_the_origin_the_proxy_was_told_last(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + OVERLAPPING,
        scenario="""
          browser.serve(holding("GET", "/api/attacker/"));
          await browser.choose("origin", "edge-br");
          await browser.choose("origin", "edge-hk");
          const moving = shown();
          while (held.length) {
            const latest = held.pop();
            latest.resolve(healthy(latest.request));
            await browser.settle();
          }
          browser.serve(healthy);
          const lastMove = moves().pop();
          return {moving, lastMove, after: shown(), recorded: await recordWindow()};
        """,
    )
    [case] = seen["result"]["recorded"]

    assert seen["errors"] == []
    assert seen["result"]["moving"]["toggle"] is True, (
        "Start could be pressed while the proxy was still being moved, and the "
        "window would be recorded from the origin it was leaving"
    )
    assert seen["result"]["lastMove"] == "edge-hk"
    assert seen["result"]["after"] == {
        "select": "edge-hk", "proxied": "103.152.220.2", "toggle": False,
    }
    assert case["source_ip"] == "103.152.220.2", (
        "the proxy was last told Hong Kong, and an earlier box read that answered "
        "late put the window back on Sao Paulo, whose alerts it would never match"
    )
    assert case["meta"]["origin"] == "edge-hk"

def test_a_window_cannot_start_from_the_box_of_an_origin_the_proxy_has_left(client):
    reason = "docker did not answer in time"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + f"""
          const unreadableBox = (request) =>
            request.method === "GET" && request.route === "/api/attacker/"
              ? {{status: 503, body: {{detail: {js(reason)}}}}}
              : healthy(request);
        """,
        scenario="""
          const before = browser.element("window-toggle").disabled;
          browser.serve(unreadableBox);
          await browser.choose("origin", "edge-br");
          await browser.click("window-toggle");
          return {
            before,
            toggle: browser.element("window-toggle").disabled,
            status: browser.text("window-status"),
            labelled: browser.requests.filter((r) => r.route === "/api/attacker/label/").length,
          };
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"] is False
    assert seen["result"]["status"] == english("red.window.status.unavailable", reason)
    assert seen["result"]["toggle"] is True, (
        "the proxy moved to Sao Paulo and its box could not be read, and Start "
        "stayed ready to record from the Moscow address the terminal had left"
    )
    assert seen["result"]["labelled"] == 0

HELD_CHECK = """
let release;
const answered = new Promise((resolve) => { release = resolve; });
const holding = (method, route) => (request) =>
  request.method === method && request.route === route
    ? answered.then(() => healthy(request))
    : healthy(request);
const sent = (method, route) =>
  browser.requests.filter((r) => r.method === method && r.route === route).length;
const CHECK = ["POST", "/api/sessions/1/objectives/"];
ANSWERS["POST /api/sessions/1/attacks/"] = (request) => ({case: request.body.case});
"""

@pytest.mark.parametrize("method, route, achieved", [
    ("POST", "/api/sessions/1/objectives/", 0),
    ("GET", "/api/sessions/1/objectives/", 0),
    ("GET", "/api/wargames/juice-shop/objectives/", 1),
])
def test_a_slow_objective_check_is_not_overtaken_by_the_next_one(client, method, route, achieved):
    held = f"[{js(method)}, {js(route)}]"
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + HELD_CHECK
        + f'ANSWERS["POST /api/sessions/1/objectives/"] = () => ({{achieved: {achieved}}});',
        scenario=f"""
          browser.serve(holding(...{held}));
          const before = sent(...{held});
          for (let interval = 0; interval < 4; interval += 1) await browser.poll();
          const during = sent(...{held}) - before;
          release();
          await browser.settle();
          await browser.poll();
          return {{during, after: sent(...{held}) - before}};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        f"{method} {route} did not answer for four poll intervals, and each "
        f"interval sent another beside it"
    )
    assert seen["result"]["after"] == 2, "polling stopped once the slow check finished"

def test_an_attack_fired_during_a_check_is_checked_once_that_check_ends(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + HELD_CHECK,
        scenario="""
          browser.serve(holding(...CHECK));
          await browser.poll();
          fire("sqli-login");
          await browser.settle();
          const during = sent(...CHECK);
          release();
          await browser.settle();
          return {during, after: sent(...CHECK)};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        "the attack asked for a check while one was still running and got a "
        "second one beside it"
    )
    assert seen["result"]["after"] == 2, (
        "the check that was running began before the attack landed, and the "
        "one the attack asked for was dropped instead of run after it"
    )

def test_the_red_log_stops_growing_and_keeps_the_newest_lines(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + """
          ANSWERS["GET /api/wargames/juice-shop/cases/"] = () => Array.from(
            {length: 10}, (_, n) => ({name: `case-${n}`, summary: "", malicious: true}));
          ANSWERS["POST /api/sessions/1/attacks/"] = (request) => ({case: request.body.case});
          const lines = () => browser.element("log").children;
          const runAll = async (times) => {
            for (let run = 0; run < times; run += 1) await browser.click("run-all");
          };
        """,
        scenario="""
          await runAll(50);
          const halfway = lines().length;
          await runAll(50);
          await fire("the-last-one");
          return {
            halfway,
            end: lines().length,
            newest: lines()[0].textContent,
            fired: browser.requests.filter((r) => r.route === "/api/sessions/1/attacks/").length,
          };
        """,
    )["result"]

    assert seen["fired"] == 1001
    assert seen["end"] == seen["halfway"] < 1000, (
        f"a thousand attacks left {seen['end']} lines in the log, one per attack, "
        f"and a console left open all day keeps every one of them"
    )
    assert seen["newest"] == english("red.log.sent", "the-last-one")

def test_an_objective_taken_keeps_the_category_the_operator_chose(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + """
          const objective = (key, name, category) =>
            ({key, name, category, difficulty: 1, description: "", solved: false});
          ANSWERS["GET /api/wargames/juice-shop/objectives/"] = () => [
            objective("loginAdmin", "Login Admin", "Injection"),
            objective("domXss", "DOM XSS", "XSS"),
          ];
          ANSWERS["POST /api/sessions/1/objectives/"] = () => ({achieved: 1});
          const filter = () => ({
            category: browser.element("objective-category").value,
            listed: ["Login Admin", "DOM XSS"].filter(
              (name) => browser.element("objectives").innerHTML.includes(name)),
          });
        """,
        scenario="""
          await browser.choose("objective-category", "XSS");
          const chosen = filter();
          await browser.poll();
          return {chosen, after: filter()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["chosen"] == {"category": "XSS", "listed": ["DOM XSS"]}
    assert seen["result"]["after"] == {"category": "XSS", "listed": ["DOM XSS"]}, (
        "an objective fell, the category list was drawn again, and the filter "
        "the operator had chosen went back to every category"
    )

def test_a_red_console_woken_from_sleep_checks_its_objectives_once(client):
    seen = open_page(
        client, "/red/1/",
        setup=RED_RANGE + ASLEEP,
        scenario="""
          const checks = () => count("POST", "/api/sessions/1/objectives/");
          sleep(HOUR);
          await wake();
          const woke = checks();
          await wake();
          const again = checks();
          browser.serve((request) =>
            request.method === "POST" && request.route === "/api/sessions/1/objectives/"
              ? {status: 409, body: {detail: "closed"}}
              : healthy(request));
          sleep(HOUR);
          await wake();
          const closing = checks();
          sleep(HOUR);
          await wake();
          return {woke, again, closing, closed: checks()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["woke"] == 1, (
        "the page came back after an hour and waited for its timer before it "
        "looked for objectives taken while it was away"
    )
    assert seen["result"]["again"] == 1, (
        "coming back into view and back online together checked once for each"
    )
    assert seen["result"]["closing"] == 2
    assert seen["result"]["closed"] == 2, "a closed session was checked because the page came back"

MAIN_RANGE = r"""
const WARGAMES = [{id: "juice-shop", name: "Juice Shop", description: "", cases: 3}];
const opened = (id) =>
  ({id, scenario: "juice-shop", started_at: "2026-09-23T10:00:00Z", ended_at: null});
const closing = (session) => ({...session, ended_at: "2026-09-23T11:00:00Z"});
let OPEN = [opened(7)];
let CLOSED = [];
const listing = (request) => {
  if (request.route === "/api/wargames/") return {body: WARGAMES};
  if (request.route === "/api/sessions/") {
    return {body: request.query.state === "open" ? OPEN : CLOSED};
  }
  return {status: 404, body: {detail: "not served"}};
};
browser.serve(listing);
const ids = (id) =>
  [...browser.element(id).innerHTML.matchAll(/href="\/session\/(\d+)\/"/g)].map((m) => Number(m[1]));
const listed = () => ({
  running: ids("running"),
  finished: ids("finished"),
  runningShown: !browser.element("running-panel").classList.contains("hidden"),
});
const lists = () => browser.requests.filter(
  (r) => r.route === "/api/sessions/" && r.query.state === "open").length;
"""

PLACES = r"""
const whereFrom = () => ({
  zone: column(5),
  place: column(6),
  outside: Object.fromEntries(
    browser.element("rows").innerHTML.split("<tr ").slice(1).map((row) => [
      /data-id="([^"]*)"/.exec(row)[1],
      row.split(/<td\b/)[5].includes("text-rose-300"),
    ])),
});
const MOSCOW = {zone: "Internet", outside: true, country: "Russia", city: "Moscow"};
"""

def test_an_alert_says_where_it_came_from_when_the_busiest_sources_do_not_list_it(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACES + """
          DETECTIONS = [
            alert(1, {src_ip: "5.188.10.99", ...MOSCOW}),
            alert(2, {src_ip: "172.30.0.2", zone: "Application estate", outside: false,
                      country: "", city: ""}),
          ];
        """,
        scenario="return whereFrom();",
    )

    assert seen["errors"] == []
    assert seen["result"] == {
        "zone": {"1": "Internet", "2": "Application estate"},
        "place": {"1": "Moscow, Russia", "2": "-"},
        "outside": {"1": True, "2": False},
    }, (
        "both alerts said where they came from, and the table looked their "
        "sources up in the top 25 instead, which listed neither"
    )

def test_a_new_source_is_placed_as_soon_as_its_alert_arrives(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ALERTS + PLACES,
        scenario="""
          const before = whereFrom();
          DETECTIONS.push(alert(5, {src_ip: "5.188.10.7", ...MOSCOW, city: ""}));
          ANSWERS["/api/sessions/1/top/"] = {
            sources: [{src_ip: "5.188.10.7", host: "", ...MOSCOW, city: "", alerts: 1}],
            destinations: [], signatures: [], paths: [],
          };
          await browser.poll();
          return {before, after: whereFrom()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["before"] == {"zone": {}, "place": {}, "outside": {}}
    assert seen["result"]["after"] == {
        "zone": {"5": "Internet"}, "place": {"5": "Russia"}, "outside": {"5": True},
    }, (
        "a source seen for the first time showed no zone or place until the top "
        "tables were next read, fifteen seconds later"
    )

def test_the_session_list_catches_up_with_sessions_opened_and_closed_elsewhere(client):
    seen = open_page(
        client, "/",
        setup=MAIN_RANGE,
        scenario="""
          const first = listed();
          CLOSED = [closing(OPEN[0])];
          OPEN = [opened(8)];
          await browser.poll();
          const later = listed();
          CLOSED = [closing(OPEN[0]), ...CLOSED];
          OPEN = [];
          await browser.poll();
          return {first, later, last: listed()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["first"] == {"running": [7], "finished": [], "runningShown": True}
    assert seen["result"]["later"] == {"running": [8], "finished": [7], "runningShown": True}, (
        "session 7 was closed and session 8 opened after the page was drawn, and "
        "the page went on listing 7 as in progress and never showed 8"
    )
    assert seen["result"]["last"] == {"running": [], "finished": [8, 7], "runningShown": False}

def test_a_main_page_woken_from_sleep_lists_the_sessions_once(client):
    seen = open_page(
        client, "/",
        setup=MAIN_RANGE + ASLEEP,
        scenario="""
          sleep(HOUR);
          const before = lists();
          await shown("hidden");
          const hidden = lists() - before;
          OPEN = [opened(9)];
          await wake();
          const woke = {lists: lists() - before, running: listed().running};
          await wake();
          return {hidden, woke, again: lists() - before};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["hidden"] == 0, "a page going out of sight was listed for it"
    assert seen["result"]["woke"] == {"lists": 1, "running": [9]}, (
        "the page came back after an hour and went on showing the sessions it "
        "had drawn before it slept until its timer came round"
    )
    assert seen["result"]["again"] == 1, (
        "coming back into view and back online together listed once for each"
    )

def test_a_page_brought_back_while_its_list_is_loading_does_not_load_it_twice(client):
    seen = open_page(
        client, "/",
        setup=MAIN_RANGE + ASLEEP + """
          let release;
          const answered = new Promise((resolve) => { release = resolve; });
          browser.serve((request) => request.route === "/api/sessions/"
            ? answered.then(() => listing(request))
            : listing(request));
        """,
        scenario="""
          sleep(HOUR);
          await wake();
          await browser.poll();
          const during = lists();
          release();
          await browser.settle();
          await browser.poll();
          return {during, after: lists()};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["during"] == 1, (
        "the list was still loading when the page came back into view, and a "
        "second load started beside it"
    )
    assert seen["result"]["after"] == 2, "refreshing stopped once the slow list arrived"

def test_a_session_list_that_answers_again_clears_its_own_error_only(client):
    seen = open_page(
        client, "/",
        setup=MAIN_RANGE + """
          const noCatalogue = (answer) => (request) => request.route === "/api/wargames/"
            ? {status: 503, body: {detail: "the catalogue did not answer"}}
            : answer(request);
          browser.serve(noCatalogue((request) => request.route === "/api/sessions/"
            ? {status: 503, body: {detail: "the database is locked"}}
            : listing(request)));
        """,
        scenario="""
          const said = (id) =>
            browser.element(id).classList.contains("hidden") ? "" : browser.text(id);
          const panels = () => ({
            sessions: said("sessions-error"), start: said("start-error"), listed: listed(),
          });
          const failing = panels();
          browser.serve(noCatalogue(listing));
          await browser.poll();
          return {failing, back: panels()};
        """,
    )
    scenarios_down = english(
        "main.unavailable", english("main.the_scenarios"), "the catalogue did not answer")

    assert seen["errors"] == []
    assert seen["result"]["failing"]["sessions"] == english(
        "main.unavailable", english("main.the_sessions"), "the database is locked")
    assert seen["result"]["failing"]["start"] == scenarios_down
    assert seen["result"]["back"] == {
        "sessions": "",
        "start": scenarios_down,
        "listed": {"running": [7], "finished": [], "runningShown": True},
    }, (
        "the session list answered again, and the page either kept saying it "
        "could not be read or took the scenarios' own error away with it"
    )

def test_a_session_that_could_not_be_closed_says_why(client):
    reason = "session 1 closed at 2026-09-23T11:00:00+00:00"
    seen = open_page(
        client, "/session/1/",
        setup=f"""
          browser.serve((request) =>
            request.method === "POST" && request.route === "/api/sessions/1/close/"
              ? {{status: 409, body: {{detail: {js(reason)}}}}}
              : {{status: 404, body: {{}}}});
        """,
        scenario="""
          await browser.click("close");
          await browser.click("confirm-close");
          return browser.text("closed");
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == english("session.close.failed", reason), (
        "the session was already closed elsewhere, and the page hid that and "
        "told the operator to check the platform was running and try again"
    )

NEVER_ANSWERED = """
let unanswered = true;
const hanging = (answer, held) => (request) =>
  unanswered && held(request) ? new Promise(() => {}) : answer(request);
const stalling = (answer, held) => (request) =>
  unanswered && held(request) ? {...answer(request), bodyNeverArrives: true} : answer(request);
"""
MINUTE = 60 * 1000

@pytest.mark.parametrize("lost", ["hanging", "stalling"])
def test_a_request_the_platform_never_answers_is_given_up_as_unreachable(client, lost):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + INDICATOR + NEVER_ANSWERED + f"""
          const isIngest = (request) => request.route === "/api/sessions/1/ingest/";
          browser.serve({lost}(healthy, isIngest));
          const ingests = () => browser.requests.filter(isIngest).length;
        """,
        scenario=f"""
          await browser.wait({MINUTE});
          const waiting = {{ingests: ingests(), indicator: indicator()}};
          await browser.wait({MINUTE // 2});
          const givenUp = {{ingests: ingests(), indicator: indicator()}};
          unanswered = false;
          await browser.poll();
          return {{waiting, givenUp, back: {{ingests: ingests(), indicator: indicator()}}}};
        """,
    )
    waiting, given_up, back = (seen["result"][k] for k in ("waiting", "givenUp", "back"))

    assert seen["errors"] == []
    assert waiting["ingests"] == 1
    assert waiting["indicator"]["label"] == english("blue.live.on"), (
        "an ingest a minute old was given up, and ingest can wait that long "
        "behind a rule change before it answers"
    )
    assert given_up["indicator"]["label"] == english("blue.live.unreachable"), (
        "one ingest never answered and the console went on saying Live without "
        "ever polling again"
    )
    assert given_up["indicator"]["title"] == english("common.no_answer_within", 90)
    assert back["ingests"] == 2
    assert back["indicator"]["label"] == english("blue.live.on")

@pytest.mark.parametrize("path, served, answer, held", [
    pytest.param("/blue/1/", BLUE_RANGE, "healthy",
                 'request.route === "/api/sessions/1/ingest/"', id="blue-ingest"),
    pytest.param("/red/1/", RED_RANGE, "healthy",
                 'request.method === "POST" && request.route === "/api/sessions/1/objectives/"',
                 id="red-objective-check"),
    pytest.param("/", MAIN_RANGE, "listing",
                 'request.route === "/api/sessions/" && request.query.state === "open"',
                 id="main-session-list"),
])
def test_a_poll_whose_request_is_never_answered_polls_again_once_it_gives_up(
        client, path, served, answer, held):
    seen = open_page(
        client, path,
        setup=served + NEVER_ANSWERED + f"""
          const held = (request) => {held};
          browser.serve(hanging({answer}, held));
          const polled = () => browser.requests.filter(held).length;
        """,
        scenario=f"""
          for (let interval = 0; interval < 4; interval += 1) await browser.poll();
          const waiting = polled();
          await browser.wait({10 * MINUTE});
          unanswered = false;
          await browser.poll();
          return {{waiting, after: polled()}};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"]["waiting"] == 1
    assert seen["result"]["after"] == 2, (
        f"{path} sent one poll the platform never answered and never polled again"
    )

RANGE_WORK = """
let release;
const released = new Promise((resolve) => { release = resolve; });
const holding = (answer, method, route) => (request) =>
  request.method === method && request.route === route
    ? released.then(() => answer(request))
    : answer(request);
"""

@pytest.mark.parametrize("path, served, answer, route, act, shown, expected", [
    pytest.param(
        "/red/1/", RED_RANGE + 'ANSWERS["POST /api/sessions/1/attacks/"] = () => ({});',
        "healthy", "/api/sessions/1/attacks/", 'fire("sqlmap-boolean-blind");',
        'browser.text("log")', english("red.log.sent", "sqlmap-boolean-blind"), id="fire"),
    pytest.param(
        "/blue/1/", BLUE_RANGE + RULES_RANGE,
        "routed", "/api/rules/apply/", 'browser.click("apply");',
        'browser.text("output")', english("blue.rules.applied"), id="apply"),
    pytest.param(
        "/blue/1/", BLUE_RANGE + RULES_RANGE
        + 'ROUTES["POST /api/rules/validate/"] = () => ({body: {ok: true, output: "valid"}});',
        "routed", "/api/rules/validate/", 'browser.click("validate");',
        'browser.text("output")', "valid", id="validate"),
    pytest.param(
        "/blue/1/", BLUE_RANGE + RULES_RANGE,
        "routed", "/api/rules/suppressions/",
        'openDrawer(7).then(() => browser.click("suppress"));',
        'browser.element("editor").value', f"# {RULE}", id="suppress"),
    pytest.param(
        "/blue/1/", BLUE_RANGE + RULES_RANGE + 'ANSWERS["/api/rules/"] = SILENCED_RULES;',
        "routed", "/api/rules/suppressions/1/restore/", "restoreSuppression(1);",
        'browser.element("editor").value', RULE, id="restore"),
])
def test_range_work_is_not_given_up_while_the_range_is_still_doing_it(
        client, path, served, answer, route, act, shown, expected):
    seen = open_page(
        client, path,
        setup=served + RANGE_WORK + f"browser.serve(holding({answer}, 'POST', {js(route)}));",
        scenario=f"""
          {act}
          await browser.settle();
          await browser.wait({10 * MINUTE});
          release();
          await browser.settle();
          await browser.settle();
          return {shown};
        """,
    )

    assert seen["errors"] == []
    assert seen["result"] == expected, (
        f"POST {route} runs a tool or reloads the sensor, which can take ten "
        f"minutes, and the console gave it up while the range was still doing it"
    )


def test_the_top_tables_catch_up_with_alerts_that_arrived_just_after_the_page_opened(client):
    seen = open_page(
        client, "/blue/1/",
        setup=BLUE_RANGE + ASLEEP + """
          const ARRIVED = [{
            id: 1, detection_id: "a1", source: "suricata", signature: "FSL SQLi attempt - URI",
            severity: 1, timestamp: "2026-09-25T00:00:00Z", src_ip: "5.188.10.5", marker: null,
            dest_ip: "5.188.10.4", dest_port: 80, method: "POST", path: "/rest/user/login",
            zone: "Internet", outside: true, country: "Russia", city: "",
          }];
          const TOP = {
            sources: [{src_ip: "5.188.10.5", host: "", zone: "Internet", outside: true,
                       country: "Russia", country_code: "RU", city: "", alerts: 1}],
            destinations: [], signatures: [], paths: [],
          };
        """,
        scenario="""
          ANSWERS["/api/sessions/1/detections/"] = ARRIVED;
          ANSWERS["/api/sessions/1/top/"] = TOP;
          await browser.poll();
          ANSWERS["/api/sessions/1/detections/"] = [];
          sleep(16000);
          await browser.poll();
          sleep(16000);
          await browser.poll();
          return browser.element("sources").innerHTML;
        """,
    )

    assert seen["errors"] == []
    assert "5.188.10.5" in seen["result"], (
        "the page read the top tables when it opened, before any alert, and the "
        "first alerts arrived inside the fifteen seconds it waits between "
        "reads; that read was skipped, not put off, and with no newer alert "
        "nothing asked again - the tables stayed empty beside a total of 4 "
        "(seen in a real browser on session 1484)"
    )
