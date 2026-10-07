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

    assert state["selected"] == ["pfsense"], "the first pane is not selected on load"
    assert state["src"] == "http://console.test:8080/", state["src"]
    assert state["consoles"] == [], (
        "no pane frames a noVNC console any more; pfSense is a reverse-proxy "
        f"origin, framed directly like ELK and the WAF: {state['consoles']}"
    )

def test_the_pfsense_pane_frames_a_reverse_proxy_on_its_own_origin(client):
    seen = open_page(client, "/blue/1/", setup=CONSOLES, scenario="""
      await browser.click('[data-pane="pfsense"]');
    """ + READ)
    state = _state(seen["result"])

    assert state["selected"] == ["pfsense"]
    assert state["src"] == "http://console.test:8080/", (
        "pfSense is framed through the platform's own reverse-proxy on a "
        f"dedicated port, a distinct origin from the console: {state['src']}"
    )
    proxy_origin = "/".join((state["src"] or "").split("/", 3)[:3])
    assert proxy_origin != "http://console.test", (
        "the proxy origin must differ from the console origin (by port) so the "
        "browser frames pfSense cross-origin, not under the console origin"
    )
    assert proxy_origin.endswith(":8080"), proxy_origin

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


REVEALED = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/score/") {
    return {body: {game: {
      revealed: true, balance: 3.5, attacker: 5.0, defender: 8.5,
      speed: 0.7, accuracy: 0.5, coverage: 0.6, response: null,
      weights: {speed: 0.25, accuracy: 0.3, coverage: 0.2, response: 0.25},
    }}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def test_a_closed_session_reveals_the_zero_sum_scoreboard(client):
    seen = open_page(client, "/session/1/", setup=REVEALED, scenario="""
      return {
        text: browser.text('scoreboard'),
        hidden: browser.element('scoreboard').classList.contains('hidden'),
        closeHidden: browser.element('close').classList.contains('hidden'),
      };
    """)
    result = seen["result"]

    assert result["hidden"] is False, "a closed session must show its scoreboard"
    assert result["closeHidden"] is True, "a closed session offers no second close"
    assert english("session.score.defence_ahead", "3.5") in result["text"], result["text"]
    for key in ("speed", "accuracy", "coverage", "response"):
        assert english(f"session.score.pillar.{key}") in result["text"], key

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

    assert {"case_id": None} in seen["result"]["clears"], (
        "the red console must POST a null attacker label on load so a window left "
        "open by a crashed or reloaded page does not mis-attribute later traffic: "
        f"{seen['result']['clears']}"
    )
