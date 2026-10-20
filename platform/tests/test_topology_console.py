import json
import pathlib
from json import dumps as js

import pytest

from tests.browser import open_page

pytestmark = pytest.mark.django_db

PROJECT = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "deploy/topology/range-openstack.gns3").read_text()
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
};
"""

def test_the_topology_pane_frames_the_gns3_web_ui_through_its_read_only_sign_in(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/map.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
    """ + READ)

    assert seen["errors"] == []
    assert seen["result"]["frame"] == "http://console.test:3080/static/web-ui/map.html?project=p"
    assert seen["result"]["frameShown"] == "block"


@pytest.mark.parametrize("language", ["en", "ko"])
def test_the_topology_pane_asks_for_the_project_drawn_in_the_console_s_language(client, language):
    web_ui = {"port": 3080, "path": "/static/web-ui/map.html?project=p"}
    chosen = f"localStorage.setItem('fsl-language', '{language}');\n"
    seen = open_page(client, "/blue/1/", setup=chosen + serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return browser.requests.filter((r) => r.route === '/api/topology/').map((r) => [r.query.language, r.query.session]);
    """)

    assert seen["errors"] == []
    assert seen["result"] == [[language, "1"]], "the pane asks for the map of its own session's range"
