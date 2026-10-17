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

def test_a_closed_session_reports_what_was_taken_and_what_the_defence_judged_counting_one_case_once(client):
    seen = open_page(client, "/session/1/", setup=CLOSED, scenario="""
      return {objectives: browser.text('objective-rows'), lost: browser.text('lost-count'),
              judged: browser.text('judgement')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["lost"] == "1 / 2"
    assert english("score.lost_unseen") in result["objectives"] and "8" in result["objectives"], (
        "lost and unnoticed costs double the difficulty"
    )
    assert english("score.attacks", 8, 7) in result["judged"]
    assert english("score.attacks_missed", 1, english("case.board-sqli-orderby-sqlmap")) in result["judged"]
    assert english("score.benign", 4, 3) in result["judged"]
    assert english("score.one_case_once") in result["judged"]
    assert english("score.not_corroborated", 7, 1) in result["judged"]

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

def _session_7(kind):
    return f"""
      browser.serve((request) => {{
        if (request.route === "/api/sessions/7/") return {{body: {{id: 7, scenario: "board", kind: "{kind}",
          kali_terminal: "/vm-terminal/fsl-kali/?arg=7", site: {{port: 8002, path: "/site/7/board.com/"}}}}}};
        return {{status: 404, body: {{detail: "not served"}}}};
      }});
    """

SHOWN_PANES = """
      return {kali: browser.element('kali-frame').getAttribute('src'),
              panes: document.querySelectorAll('.pane-tab:not(.hidden)').map((tab) => tab.dataset.pane),
              asked: browser.requests.map((r) => r.method + " " + r.route)};
"""

def test_the_red_console_is_the_kali_terminal_and_the_website_and_runs_no_prepared_attack(client):
    seen = open_page(client, "/red/7/", setup=_session_7("wargame"), scenario=SHOWN_PANES)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["panes"] == ["kali", "site"]
    assert result["kali"] == "/vm-terminal/fsl-kali/?arg=7"
    assert not [asked for asked in result["asked"] if "/cases/" in asked or "/attacks/" in asked
                or "/api/attacker/" in asked], result["asked"]

@pytest.mark.parametrize("kind, shown", [("lesson", True), ("scenario", True), ("wargame", False)])
def test_the_blue_console_carries_kali_for_practice_and_not_in_a_wargame(client, kind, shown):
    seen = open_page(client, "/blue/7/", setup=_session_7(kind), scenario="""
      const panes = document.querySelectorAll('.pane-tab:not(.hidden)').map((tab) => tab.dataset.pane);
      if (panes.includes("kali")) await browser.click('[data-pane="kali"]');
      return {panes, kali: browser.element('kali-frame').getAttribute('src'),
              line: !browser.element('rail-line').classList.contains('hidden')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert ("kali" in result["panes"]) is shown and result["line"] is shown, (
        "the defender in a person-against-person wargame must not hold the attacker's shell"
    )
    assert result["kali"] == ("/vm-terminal/fsl-kali/?arg=7" if shown else None)

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

@pytest.mark.parametrize("ingest_status", ["200", "500"])
def test_closing_a_session_ingests_first_and_closes_even_when_the_ingest_fails(client, ingest_status):
    seen = open_page(
        client, "/session/1/",
        setup=OPEN_SESSION.replace("INGEST_STATUS", ingest_status), scenario=CLOSE_SCENARIO,
    )
    routes = seen["result"]

    assert "POST /api/sessions/1/ingest/" in routes, routes
    assert "POST /api/sessions/1/close/" in routes, routes
    assert routes.index("POST /api/sessions/1/ingest/") < routes.index("POST /api/sessions/1/close/")

def test_the_waf_pane_frames_the_session_s_own_waf_terminal(client):
    seen = open_page(client, "/blue/7/", setup="""
      browser.serve((request) => {
        if (request.route === "/api/sessions/7/") return {body: {id: 7, waf_terminal: "/waf-terminal/7/"}};
        return {status: 404, body: {detail: "not served"}};
      });
    """, scenario="""
      await browser.click('[data-pane="waf"]');
      return browser.element('pane-frame').getAttribute('src');
    """)

    assert seen["result"] == "/waf-terminal/7/", (
        f"the WAF pane must open the terminal the session names, not a shared one: {seen['result']}"
    )


RESETTING = """
browser.serve((request) => {
  if (request.route === "/api/range/ready/") {
    return {body: {ready: false, max_sessions: 2, slot: {number: 1, session: null, phase: "RESETTING",
      blocked: ["the range is resetting after the last session closed"]}}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_the_home_page_says_the_practice_network_is_resetting_in_the_learner_s_words(client):
    seen = open_page(client, "/", setup=RESETTING, scenario="""
      await browser.wait(500);
      return browser.text('range-blocked');
    """)

    assert seen["errors"] == []
    assert seen["result"] == english("range.resetting"), (
        "the home page showed the readiness API's operator reason instead of the learner's line"
    )
