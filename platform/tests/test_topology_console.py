import json
import pathlib
from json import dumps as js

import pytest

from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

PROJECT = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "deploy/topology/range-docker.gns3").read_text()
)
def serving(web_ui):
    return f"""
browser.serve((request) => {{
  if (request.route === "/api/topology/") return {{body: {{source: "gns3", status: "", detail: "",
    project: {js(PROJECT)}, web_ui: {js(web_ui)}}}}};
  return {{status: 404, body: {{detail: "not served"}}}};
}});
"""

READ = """
return {
  frame: browser.element('topology-frame').getAttribute('src'),
  frameShown: browser.element('topology-frame').style.display,
  said: browser.text('topology-said'),
  asked: browser.requests.map((r) => r.route).filter((route) => route.includes('topology')),
  pane: browser.element('topology').innerHTML,
};
"""

def test_the_topology_pane_frames_the_gns3_web_ui_through_its_read_only_sign_in(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
    """ + READ)

    assert seen["errors"] == []
    assert seen["result"]["frame"] == "http://console.test:3080/static/web-ui/fsl-auditor.html?project=p"
    assert seen["result"]["frameShown"] == "block"

def test_the_topology_pane_is_the_network_map_alone_with_its_fit_button(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      const opened = {map: browser.element('topology-gns3').getAttribute('aria-selected'),
                      frame: browser.element('topology-frame').style.display,
                      fit: browser.element('topology-fit').style.display,
                      fitSays: browser.text('topology-fit'),
                      tabs: browser.element('topology').querySelectorAll('.tab').length};
      await browser.click('#topology-fit');
      return opened;
    """)
    template = (pathlib.Path(__file__).resolve().parents[1] / "console/templates/console/blue_topology.html").read_text()

    assert seen["errors"] == []
    assert seen["result"] == {"map": "true", "frame": "block", "fit": "", "fitSays": english("topology.fit"), "tabs": 1}
    assert "topology-follow" not in template and "topology-request" not in template

@pytest.mark.parametrize("language", ["en", "ko"])
def test_the_fit_button_of_the_map_reads_in_the_console_s_language(client, language):
    from tests.test_strings import tables
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    chosen = f"localStorage.setItem('fsl-language', '{language}');\n"
    seen = open_page(client, "/blue/1/", setup=chosen + serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return browser.text('topology-fit');
    """)

    assert seen["errors"] == []
    assert seen["result"] == tables()[language]["topology.fit"] != ""
    assert "GNS3" not in seen["result"]

def test_without_gns3_the_pane_says_the_map_is_not_open_and_frames_nothing(client):
    seen = open_page(client, "/blue/1/", setup=serving(None), scenario="""
      await browser.click('[data-pane="topology"]');
    """ + READ)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["frame"] is None and result["frameShown"] == "none"
    assert result["said"] == english("topology.no_web_ui")
    assert result["asked"] == ["/api/topology/"], "the pane reads the map and nothing that follows a request"
    assert "topology-svg" not in result["pane"] and "topology-hops" not in result["pane"]

@pytest.mark.parametrize("language", ["en", "ko"])
def test_the_topology_pane_asks_for_the_project_drawn_in_the_console_s_language(client, language):
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    chosen = f"localStorage.setItem('fsl-language', '{language}');\n"
    seen = open_page(client, "/blue/1/", setup=chosen + serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return browser.requests.filter((r) => r.route === '/api/topology/').map((r) => [r.query.language, r.query.session]);
    """)

    assert seen["errors"] == []
    assert seen["result"] == [[language, "1"]], "the pane asks for the map of its own session's range"

def test_the_map_tab_reads_network_map_and_nothing_a_learner_reads_names_the_map_tool(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return {tab: browser.text('topology-gns3'), title: browser.element('topology-frame').title,
              pane: browser.element('topology').innerText || browser.text('topology')};
    """)
    template = (pathlib.Path(__file__).resolve().parents[1] / "console/templates/console/strings.html").read_text()
    shown = [line for line in template.splitlines() if line.strip().startswith('"topology.')
             or line.strip().startswith('"lesson.range.')]

    assert seen["errors"] == []
    assert seen["result"]["tab"] == english("topology.view.map") == "Network map"
    assert seen["result"]["title"] == "Network map"
    assert "GNS3" not in seen["result"]["pane"]
    assert [line for line in shown if "GNS3" in line or "fsl-" in line] == []
    assert "topology/addresses" not in (pathlib.Path(__file__).resolve().parents[1] / "fsl/urls.py").read_text()

@pytest.mark.parametrize("language", ["en", "ko"])
def test_the_map_that_shows_kali_s_dragon_says_whose_trademark_it_is(client, language):
    from tests.test_strings import tables
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    chosen = f"localStorage.setItem('fsl-language', '{language}');\n"
    seen = open_page(client, "/blue/1/", setup=chosen + serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return browser.text('topology-trademark');
    """)

    assert seen["errors"] == []
    assert seen["result"] == tables()[language]["topology.trademark"]
    assert "KALI LINUX™" in seen["result"] and "OffSec" in seen["result"]
    assert english("topology.trademark") == "KALI LINUX™ is a trademark of OffSec."
