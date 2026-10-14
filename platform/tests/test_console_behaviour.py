import re
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

CONSOLES = """
browser.serve((request) => {
  const m = /^\\/api\\/range\\/console\\/([^/]+)\\/$/.exec(request.route);
  if (m) return {body: {url: `http://nova/vnc_lite.html?host=${m[1]}`}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def _state(result):
    return {
        "selected": result["selected"],
        "src": result["src"],
        "title": result["title"],
        "consoles": [r for r in result["routes"] if r.startswith("/api/range/console/")],
    }

READ = """
return {
  selected: [...document.querySelectorAll('.pane-tab')]
    .filter((t) => t.getAttribute('aria-selected') === 'true').map((t) => t.dataset.pane),
  src: browser.element('pane-frame').getAttribute('src'),
  title: browser.text('pane-status-title'),
  routes: browser.requests.map((r) => r.route),
};
"""

def test_the_blue_console_opens_the_first_pane_on_load(client):
    seen = open_page(client, "/blue/1/", setup=CONSOLES, scenario=READ)
    state = _state(seen["result"])

    assert state["selected"] == ["elk"], "the first pane is not selected on load"
    assert state["src"] == "/kibana/", state["src"]
    assert state["consoles"] == [], (
        f"no pane frames a noVNC console; every pane is framed directly: {state['consoles']}"
    )

def test_the_elk_pane_frames_kibana_on_the_platforms_own_origin(client):
    seen = open_page(client, "/blue/1/", setup=CONSOLES, scenario="""
      await browser.click('[data-pane="elk"]');
    """ + READ)
    state = _state(seen["result"])

    assert state["selected"] == ["elk"], "selecting ELK did not move the highlight"
    assert state["src"] == "/kibana/", "Kibana is same-origin, framed directly, not over a console"
    assert state["consoles"] == [], (
        "the ELK pane must not ask for a noVNC console; no pane does any more: "
        f"{state['consoles']}"
    )


CLOSED = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", guidance: false, kind: "wargame", ready: true,
                   started_at: "2026-10-10T14:20:00Z", ended_at: "2026-10-10T15:02:00Z",
                   result: {objectives: {lost: 1, undetected: 1, total: 3}, scenario: null}}};
  }
  if (request.route === "/api/wargames/board/objectives/") {
    return {body: [
      {key: "board-auth-user-partial", name: "Board accounts (partial)", difficulty: 2},
      {key: "board-auth-user-admin", name: "Board admin account", difficulty: 4},
    ]};
  }
  if (request.route === "/api/sessions/1/score/") {
    return {body: {tp: 7, fp: 1, fn: 1, tn: 3, warnings: [],
      breaches: [{key: "board-auth-user-admin", difficulty: 4, detected: false}],
      per_case: [
        ...["a1", "a2", "a3", "a4", "a5", "a6", "a7"].map((name) => ({name, malicious: true, detected: true,
          detection_ids: ["d"], corroborated: name !== "a7"})),
        {name: "board-sqli-orderby-sqlmap", malicious: true, detected: false, detection_ids: [], corroborated: null},
        {name: "board-normal-search-with-apostrophe", malicious: false, detected: true, detection_ids: ["x", "y"],
         corroborated: null},
        ...["b1", "b2", "b3"].map((name) => ({name, malicious: false, detected: false, detection_ids: [],
          corroborated: null})),
      ],
      game: {revealed: true, balance: 3.5}}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_closed_session_leads_with_what_was_taken_then_says_in_plain_sentences_what_the_defence_judged(client):
    seen = open_page(client, "/session/1/", setup=CLOSED, scenario="""
      return {
        objectives: browser.text('objective-rows'), lost: browser.text('lost-count'),
        judged: browser.text('judgement'), cases: browser.text('case-rows'),
        page: browser.text('scoreboard'),
        hidden: browser.element('scoreboard').classList.contains('hidden'),
        consoles: browser.element('consoles').classList.contains('hidden'),
        closeHidden: browser.element('close').classList.contains('hidden'),
      };
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["hidden"] is False and result["consoles"] is True, "a closed session shows its result"
    assert result["closeHidden"] is True, "a closed session offers no second close"
    assert result["lost"] == "1 / 2"
    assert english("objective.board-auth-user-admin") in result["objectives"]
    assert english("score.lost_unseen") in result["objectives"] and "8" in result["objectives"], (
        "lost and unnoticed costs double the difficulty"
    )
    assert english("score.attacks", 8, 7) in result["judged"]
    assert english("score.attacks_missed", 1, "board-sqli-orderby-sqlmap") in result["judged"]
    assert english("score.benign", 4, 3) in result["judged"]
    assert english("score.benign_blocked", 1, english("case.board-normal-search-with-apostrophe")) in result["judged"]
    assert english("score.one_case_once") in result["judged"]
    assert english("score.not_corroborated", 7, 1) in result["judged"]
    assert not re.search(r"\b(TP|FP|FN|TN)\b", result["page"]), "no scoreboard labels on a page a person reads"
    assert "Zero-sum" not in result["page"] and "3.5" not in result["page"]

FOUNDATION_CLOSED = CLOSED.replace(
    "guidance: false, kind: \"wargame\"",
    "guidance: true, kind: \"lesson\", lesson_id: \"f1\", defense: \"minimal\", lesson: {text: \"lesson.range\", steps: []}")

def test_a_closed_foundation_shows_no_verdict_and_offers_to_restart_the_lesson(client):
    seen = open_page(client, "/session/1/", setup=FOUNDATION_CLOSED, scenario="""
      const hidden = browser.element('verdict').classList.contains('hidden');
      const label = browser.text('restart');
      const badges = browser.text('session-badges');
      await browser.click('restart');
      return {hidden, restart: label, badges,
              posted: browser.requests.filter((r) => r.method === 'POST').map((r) => r.body)};
    """)

    assert seen["errors"] == []
    assert seen["result"]["hidden"] is True, "a foundation is judged by its steps, so a closed one shows no verdict banner"
    assert english("kind.lesson") in seen["result"]["badges"]
    assert seen["result"]["restart"] == english("session.restart.lesson")
    assert seen["result"]["posted"][0] == {"scenario": "board", "guidance": True, "lesson": "f1", "defense": "minimal"}

SCENARIO_CLOSED = CLOSED.replace(
    "guidance: false, kind: \"wargame\"", "guidance: false, kind: \"scenario\", course_scenario: \"2.1\"")

def test_a_closed_scenario_says_beside_its_verdict_which_help_was_used(client):
    seen = open_page(client, "/session/1/", setup=SCENARIO_CLOSED.replace(
        "scenario: null}", "scenario: {passed: true, fix: null, windows: 1, helped: [\"hint\", \"do\"]}}"), scenario="""
      return browser.text('verdict');
    """)

    assert "PASS" in seen["result"]
    assert english("result.helped.hint") in seen["result"] and english("result.helped.do") in seen["result"]

def test_the_main_page_says_beside_a_pass_which_help_was_used(client):
    seen = open_page(client, "/", setup=FULL_RANGE.replace(
        "helped: []}}},", "helped: [\"do\"]}}},"), scenario="""
      return browser.text('finished');
    """)

    assert "PASS" in seen["result"] and english("result.helped.do") in seen["result"]
    assert english("result.helped.hint") not in seen["result"]

SCORE_FAILS_ONCE = CLOSED.replace("browser.serve((request) => {", """
let scored = 0;
browser.serve((request) => {
  if (request.route === "/api/sessions/1/score/" && scored++ === 0) {
    return {status: 503, body: {detail: "database is locked"}};
  }""", 1)

def test_a_score_that_did_not_load_says_so_instead_of_calling_every_objective_kept(client):
    seen = open_page(client, "/session/1/", setup=SCORE_FAILS_ONCE, scenario="""
      const first = {objectives: browser.text('objective-rows'), lost: browser.text('lost-count'),
                     judged: browser.text('judgement')};
      await browser.wait(5000);
      return {first, then: {objectives: browser.text('objective-rows'), lost: browser.text('lost-count')},
              asked: browser.requests.filter((r) => r.route === "/api/sessions/1/score/").length};
    """)
    first, then = seen["result"]["first"], seen["result"]["then"]

    assert seen["errors"] == []
    assert english("score.kept") not in first["objectives"], (
        "the score did not load and the table still said every objective was kept, "
        "while the header said some were lost"
    )
    assert english("score.unavailable", "database is locked") in first["objectives"]
    assert first["lost"] == "—"
    assert seen["result"]["asked"] == 2, "the page did not read the score again"
    assert then["lost"] == "1 / 2" and english("score.lost_unseen") in then["objectives"]

def test_a_score_that_answered_without_its_tables_is_not_read_as_nothing_lost(client):
    seen = open_page(client, "/session/1/", setup=CLOSED.replace(
        'if (request.route === "/api/sessions/1/score/") {', 'if (request.route === "/api/sessions/1/score/") {\n'
        '    return {body: {}};'), scenario="""
      return browser.text('objective-rows');
    """)

    assert english("score.kept") not in seen["result"]
    assert english("score.retrying") in seen["result"]

def test_the_second_score_says_how_many_customer_requests_the_defence_blocked(client):
    seen = open_page(client, "/session/1/", setup=CLOSED.replace(
        "game: {revealed: true, balance: 3.5}",
        "customers: {sent: 600, served: 590, blocked: 9, unanswered: 1, other: 0, alerted: 12, "
        "blocked_actions: {\"search-unusual\": 9}}, game: {revealed: true, balance: 3.5}"), scenario="""
      return browser.text('judgement');
    """)

    assert english("score.customers", 600, 9) in seen["result"]
    assert english("score.customers_action", english("traffic.action.search-unusual"), 9) in seen["result"]
    assert english("score.customers_unanswered", 1) in seen["result"]
    assert english("score.customers_note") in seen["result"]

OPEN_WITH_TRAFFIC = """
location.search = "?traffic";
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, scenario: "board", guidance: false, kind: "wargame", ready: true,
                   started_at: "2026-10-10T14:20:00Z", ended_at: null, result: null}};
  }
  if (request.route === "/api/sessions/1/traffic/") {
    const running = request.method === "PUT";
    return {body: {declared: true, profiles: ["community", "plain"], running, rate: running ? request.body.rate : null,
                   profile: "community", sent: running ? 0 : 42, blocked: 3, error: ""}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_the_customer_traffic_toggle_is_offered_only_for_testing(client):
    hidden = open_page(client, "/session/1/", setup=OPEN_WITH_TRAFFIC.replace('location.search = "?traffic";', ""),
                       scenario="return browser.element('traffic').classList.contains('hidden');")
    shown = open_page(client, "/session/1/", setup=OPEN_WITH_TRAFFIC, scenario="""
      const before = browser.text('traffic-status');
      await browser.force('#traffic-rate', '2');
      await browser.click('#traffic-start');
      const put = browser.requests.find((r) => r.method === "PUT");
      return {hidden: browser.element('traffic').classList.contains('hidden'), before, put: put && put.body,
              after: browser.text('traffic-status')};
    """)

    assert hidden["result"] is True, "a learner's session page offered the customer traffic switch"
    assert shown["errors"] == []
    assert shown["result"]["hidden"] is False
    assert shown["result"]["before"] == english("traffic.status", english("traffic.stopped"), 0, 42, 3)
    assert shown["result"]["put"] == {"rate": 2, "profile": "community"}
    assert shown["result"]["after"].startswith(english("traffic.running"))

def test_an_open_session_shows_no_scoreboard_and_offers_close(client):
    seen = open_page(client, "/session/1/", scenario="""
      return {
        hidden: browser.element('scoreboard').classList.contains('hidden'),
        closeHidden: browser.element('close').classList.contains('hidden'),
      };
    """)
    result = seen["result"]

    assert result["hidden"] is True, "an open session withholds the scoreboard"
    assert result["closeHidden"] is False, "an open session can be closed"


def test_the_waf_pane_frames_the_web_ssh_terminal(client):
    seen = open_page(client, "/blue/1/", setup=CONSOLES, scenario="""
      await browser.click('[data-pane="waf"]');
    """ + READ)
    state = _state(seen["result"])

    assert state["selected"] == ["waf"], "selecting WAF did not move the highlight"
    assert state["src"] == "/vm-terminal/fsl-waf/", (
        "the WAF pane is a web SSH terminal, framed directly, not a noVNC console: "
        f"{state['src']}"
    )


def test_the_red_console_clears_a_stale_attacker_label_on_load(client):
    seen = open_page(client, "/red/1/", scenario="""
      return {
        clears: browser.requests.filter(
          (r) => r.route === '/api/attacker/label/' && r.method === 'POST'
        ).map((r) => r.body),
      };
    """)

    assert {"case_id": None, "session": "1"} in seen["result"]["clears"], (
        "the red console must POST a null attacker label on load so a window left "
        "open by a crashed or reloaded page does not mis-attribute later traffic: "
        f"{seen['result']['clears']}"
    )

OPEN_SESSION = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/ingest/") return {status: INGEST_STATUS, body: {}};
  if (request.route === "/api/sessions/1/close/") return {body: {}};
  return {status: 404, body: {detail: "not served"}};
});
"""

CLOSE_SCENARIO = """
      await browser.click('close');
      await browser.click('confirm-close');
      return browser.requests.map((r) => r.method + " " + r.route);
"""

def test_closing_a_session_ingests_before_it_closes(client):
    seen = open_page(
        client, "/session/1/",
        setup=OPEN_SESSION.replace("INGEST_STATUS", "200"), scenario=CLOSE_SCENARIO,
    )
    routes = seen["result"]

    assert "POST /api/sessions/1/ingest/" in routes, routes
    assert "POST /api/sessions/1/close/" in routes, routes
    assert routes.index("POST /api/sessions/1/ingest/") < routes.index("POST /api/sessions/1/close/")

def test_a_failed_ingest_still_closes_the_session(client):
    seen = open_page(
        client, "/session/1/",
        setup=OPEN_SESSION.replace("INGEST_STATUS", "500"), scenario=CLOSE_SCENARIO,
    )

    assert "POST /api/sessions/1/ingest/" in seen["result"], seen["result"]
    assert "POST /api/sessions/1/close/" in seen["result"], seen["result"]


def test_the_waf_pane_frames_the_session_s_own_waf_terminal(client):
    seen = open_page(client, "/blue/7/", setup="""
      browser.serve((request) => {
        if (request.route === "/api/sessions/7/") return {body: {id: 7, waf_terminal: "/waf-terminal/7/"}};
        return {status: 404, body: {detail: "not served"}};
      });
    """, scenario="""
      await browser.click('[data-pane="waf"]');
    """ + READ)
    state = _state(seen["result"])

    assert state["selected"] == ["waf"]
    assert state["src"] == "/waf-terminal/7/", (
        f"the WAF pane must open the terminal the session names, not a shared one: {state['src']}"
    )

FULL_RANGE = """
const closed = new Set();
browser.serve((request) => {
  if (request.route === "/api/wargames/") {
    return {body: [{id: "board", name: "Board", description: "", cases: 12, attacks: 8, benign: 4, objectives: 3,
                    foundations: [{id: "f1", order: 1, title: "lesson.range.title", goal: "lesson.range.summary",
                                   minutes: 40, level: "easy", defense: "minimal", prerequisites: [], steps: 11,
                                   learns: "lesson.range.learns"}],
                    scenarios: [],
                    category: "sql-injection", difficulty: "medium", minutes: 40}]};
  }
  if (request.route === "/api/range/ready/") return {body: {ready: true, substrate: "compose", slot: null, max_sessions: 2}};
  if (request.route === "/api/sessions/" && request.method === "POST") {
    return closed.size ? {status: 201, body: {id: 9}}
      : {status: 409, body: {detail: "2 sessions are already open on the range; close one first"}};
  }
  if (request.route === "/api/sessions/" && request.query.state === "open") {
    return {body: [
      {id: 201, scenario: "board", kind: "lesson", lesson_id: "f1", ready: true, started_at: "2026-10-10T14:20:00Z"},
      {id: 202, scenario: "board", kind: "wargame", ready: false, started_at: new Date().toISOString()},
    ].filter((row) => !closed.has(String(row.id)))};
  }
  if (request.route === "/api/sessions/" && request.query.state === "closed") {
    return {body: [
      {id: 200, scenario: "board", kind: "scenario", course_scenario: "2.1", started_at: "2026-10-10T13:13:00Z",
       ended_at: "2026-10-10T13:55:00Z", result: {objectives: {lost: 0, undetected: 0, total: 3}, scenario: {passed: true, fix: null, windows: 1, helped: []}}},
      {id: 199, scenario: "board", kind: "wargame", started_at: "2026-10-10T12:58:00Z", ended_at: "2026-10-10T13:26:00Z",
       result: {objectives: {lost: 2, undetected: 1, total: 3}, scenario: null}},
    ]};
  }
  const closing = /^\\/api\\/sessions\\/(\\d+)\\/close\\/$/.exec(request.route);
  if (closing) { closed.add(closing[1]); return {body: {id: Number(closing[1])}}; }
  if (/\\/ingest\\/$/.test(request.route)) return {body: {}};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_the_main_page_lists_running_sessions_with_their_kind_and_whether_they_are_ready(client):
    seen = open_page(client, "/", setup=FULL_RANGE, scenario="""
      return {running: browser.text('running'), capacity: browser.text('capacity'),
              finished: browser.text('finished'), card: browser.text('wargames')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert english("kind.lesson") in result["running"] and english("kind.wargame") in result["running"]
    assert english("state.ready") in result["running"]
    assert english("state.opening", 0, 80).split(" 0")[0] in result["running"], "a session still opening says so"
    assert english("main.step", 1, 11) in result["running"]
    assert result["capacity"] == english("main.capacity", 2, 2)
    assert english("main.counts", 8, 4, 3) in result["card"] and english("difficulty.medium") in result["card"]
    assert english("main.minutes", 40) in result["card"]
    assert "PASS" in result["finished"]
    assert english("result.lost", 3, 2) in result["finished"] and english("result.unseen", 1) in result["finished"]

def test_a_refused_start_says_so_under_the_button_and_offers_to_close_an_open_session(client):
    seen = open_page(client, "/", setup=FULL_RANGE, scenario="""
      await browser.click('[data-lesson="true"]');
      const failure = document.querySelector('[data-failure="board"]');
      const said = {hidden: failure.classList.contains('hidden'), text: failure.textContent,
                    offer: failure.querySelector('[data-close-open]').classList.contains('hidden')};
      await browser.click('[data-close-open]');
      const listed = [...failure.querySelectorAll('[data-close]')].map((b) => b.dataset.close);
      await browser.click('[data-close="202"]');
      const after = [...failure.querySelectorAll('[data-close]')].map((b) => b.dataset.close);
      await browser.click('[data-lesson="true"]');
      return {said, listed, after, text: failure.textContent,
              posts: browser.requests.filter((r) => r.method === 'POST').map((r) => r.route)};
    """)
    result = seen["result"]

    assert result["said"]["hidden"] is False and result["said"]["offer"] is False
    assert english("main.start_failed.full", 2, 2) in result["said"]["text"]
    assert result["listed"] == ["201", "202"]
    assert result["after"] == ["201"], "the closed session leaves the list"
    assert result["posts"] == [
        "/api/sessions/", "/api/sessions/202/ingest/", "/api/sessions/202/close/", "/api/sessions/",
    ], "closing goes through the close API, ingesting first, and the start can then be tried again"

RED = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") return {body: {id: 1, scenario: "board"}};
  if (request.route === "/api/wargames/board/cases/") {
    return {body: [
      {name: "board-sqli-search", malicious: true, summary: "GET /search/"},
      {name: "board-sqli-orderby-sqlmap", malicious: true, summary: "sqlmap -u ..."},
      {name: "board-normal-search", malicious: false, summary: "GET /search/?q=django"},
    ]};
  }
  if (request.route === "/api/sessions/1/cases/") {
    return {body: [{name: "board-sqli-search", malicious: true, meta: {status: 403}},
                   {name: "board-normal-search", malicious: false, meta: {status: 403}}]};
  }
  if (request.route === "/api/wargames/board/objectives/") {
    return {body: [{key: "board-auth-user-full", name: "Board accounts (full)", difficulty: 5},
                   {key: "board-auth-user-partial", name: "Board accounts (partial)", difficulty: 2}]};
  }
  if (request.route === "/api/sessions/1/objectives/" && request.method === "GET") {
    return {body: [{key: "board-auth-user-partial", difficulty: 2}]};
  }
  if (request.route === "/api/wargames/") return {body: [{id: "board", name: "Board", model: "loot_verified",
    covers: [], uncovered: []}]};
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_the_red_console_groups_cases_into_attacks_and_benign_with_what_their_last_run_did(client):
    seen = open_page(client, "/red/1/", setup=RED, scenario="""
      return {attacks: browser.text('attacks'), benign: browser.text('benign'),
              headings: [browser.text('attacks-heading'), browser.text('benign-heading')],
              objectives: browser.text('objectives'), taken: browser.text('taken'),
              loot: browser.element('loot-open').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["headings"] == [f"{english('red.cases.attacks')} · 2", f"{english('red.cases.benign')} · 1"]
    assert "board-sqli-search" in result["attacks"] and english("outcome.blocked") in result["attacks"]
    assert english("red.case.not_run") in result["attacks"], "a case not run yet says so"
    assert "board-normal-search" in result["benign"] and "board-sqli" not in result["benign"]
    assert result["objectives"].index(english("objective.board-auth-user-partial")) < \
        result["objectives"].index(english("objective.board-auth-user-full")), "objectives run easiest first"
    assert "1/2" in result["taken"].replace(" ", "")
    assert result["loot"] is False, "a loot-verified target offers the hash submission at the top"

def test_a_closed_scenario_shows_its_debrief_and_its_fix_on_the_score_page(client):
    from tests.test_scenario_console import DEBRIEF

    setup = SCENARIO_CLOSED.replace("scenario: null}", "scenario: {passed: false, fix: \"rule\", windows: 1, helped: []}}").replace(
        '  return {status: 404, body: {detail: "not served"}};',
        '  if (request.route === "/api/sessions/1/scenario/debrief/") return {body: ' + js(DEBRIEF) + '};\n'
        '  return {status: 404, body: {detail: "not served"}};')
    seen = open_page(client, "/session/1/", setup=setup, scenario="""
      return {hidden: browser.element('debrief').classList.contains('hidden'), text: browser.text('debrief'),
              fix: browser.text('[data-fix]')};
    """)

    assert seen["errors"] == []
    assert seen["result"]["hidden"] is False
    assert english("lesson.debrief.heading") in seen["result"]["text"]
    assert english("scenario.risk.rule") in seen["result"]["text"]
    assert seen["result"]["fix"] == f"{english('lesson.fix.rule')} {english('lesson.fix.note')}"

def test_opening_a_session_page_remembers_its_id_in_this_browser_newest_first(client):
    seen = open_page(client, "/session/1/", setup="localStorage.setItem('fsl-opened-sessions', '[5, 1, 3]');\n" + CLOSED,
                     scenario="""
      return JSON.parse(localStorage.getItem('fsl-opened-sessions'));
    """)

    assert seen["result"] == [1, 5, 3]
