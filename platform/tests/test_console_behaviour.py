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
                   result: {objectives: {lost: 1, undetected: 1, total: 3}, lesson: null}}};
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

def test_a_closed_lesson_shows_its_last_verdict_before_the_score(client):
    seen = open_page(client, "/session/1/", setup=CLOSED.replace(
        "guidance: false, kind: \"wargame\"", "guidance: true, kind: \"lesson\", lesson: {text: \"lesson.board\", steps: []}"
    ).replace("lesson: null}", "lesson: {passed: false, verified: 3, diagnosis: "
              "[[\"lesson.diag.benign_blocked\", [\"board-normal-search-with-apostrophe\", 403]]]}}"), scenario="""
      return {hidden: browser.element('verdict').classList.contains('hidden'), text: browser.text('verdict'),
              restart: browser.text('restart')};
    """)

    assert seen["result"]["hidden"] is False
    assert "FAIL" in seen["result"]["text"]
    assert english("lesson.diag.benign_blocked", "board-normal-search-with-apostrophe", 403) in seen["result"]["text"]
    assert english("score.lesson.verified", 3) in seen["result"]["text"]
    assert seen["result"]["restart"] == english("session.restart.lesson")

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
                    lesson: true, lesson_steps: 11, lesson_text: "lesson.board",
                    category: "sql-injection", difficulty: "medium", minutes: 40}]};
  }
  if (request.route === "/api/range/ready/") return {body: {ready: true, substrate: "compose", slot: null, max_sessions: 2}};
  if (request.route === "/api/sessions/" && request.method === "POST") {
    return closed.size ? {status: 201, body: {id: 9}}
      : {status: 409, body: {detail: "2 sessions are already open on the range; close one first"}};
  }
  if (request.route === "/api/sessions/" && request.query.state === "open") {
    return {body: [
      {id: 201, scenario: "board", kind: "lesson", ready: true, started_at: "2026-10-10T14:20:00Z"},
      {id: 202, scenario: "board", kind: "wargame", ready: false, started_at: new Date().toISOString()},
    ].filter((row) => !closed.has(String(row.id)))};
  }
  if (request.route === "/api/sessions/" && request.query.state === "closed") {
    return {body: [
      {id: 200, scenario: "board", kind: "lesson", started_at: "2026-10-10T13:13:00Z", ended_at: "2026-10-10T13:55:00Z",
       result: {objectives: {lost: 0, undetected: 0, total: 3}, lesson: {passed: true, verified: 1}}},
      {id: 199, scenario: "board", kind: "wargame", started_at: "2026-10-10T12:58:00Z", ended_at: "2026-10-10T13:26:00Z",
       result: {objectives: {lost: 2, undetected: 1, total: 3}, lesson: null}},
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
