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


def test_the_topology_pane_asks_for_the_map_of_its_own_session(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/map.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      return browser.requests.filter((r) => r.route === '/api/topology/').map((r) => r.query);
    """)

    assert seen["errors"] == []
    assert seen["result"] == [{"session": "1"}], "the pane asks for the map of its own session's range"

def held_back(web_ui):
    return f"""
const held = [];
browser.serve((request) => {{
  if (request.route === "/api/topology/") return new Promise((answer) => held.push(answer));
  return {{status: 404, body: {{detail: "not served"}}}};
}});
const shown = (id) => !browser.element(id).classList.contains('hidden');
const project = {{body: {{source: "gns3", status: "", detail: "", project: {js(PROJECT)}, web_ui: {js(web_ui)}}}}};
"""

def test_the_map_pane_says_it_is_loading_for_as_long_as_the_platform_is_still_loading_the_map(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/map.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=held_back(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
      const asked = shown('map-wait');
      await browser.wait(60000);
      const stillAsking = shown('map-wait');
      await browser.click('[data-pane="elk"]');
      await browser.click('[data-pane="topology"]');
      held.forEach((answer) => answer(project));
      await browser.settle();
      return {asked, stillAsking, requests: held.length, framing: shown('map-wait'),
              frame: browser.element('topology-frame').getAttribute('src')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"asked": True, "stillAsking": True, "requests": 1, "framing": True,
                              "frame": "http://console.test:3080/static/web-ui/map.html?project=p"}

def test_a_map_that_could_not_be_read_ends_the_loading_and_says_why(client):
    seen = open_page(client, "/blue/1/", setup=held_back(None), scenario="""
      await browser.click('[data-pane="topology"]');
      held[0]({status: 503, body: {detail: "GNS3 did not answer"}});
      await browser.settle();
      return {loading: shown('map-wait'), said: browser.text('topology-said')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"loading": False, "said": "GNS3 did not answer"}
