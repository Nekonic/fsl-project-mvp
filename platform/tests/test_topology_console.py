import json
import pathlib
from json import dumps as js

import pytest

from tests.browser import english, open_page

pytestmark = pytest.mark.django_db

PROJECT = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "deploy/topology/range-docker.gns3").read_text()
)
HOPS = [
    {"node": "fsl-platform", "kind": "host", "source": "172.30.0.9"},
    {"node": "estate", "kind": "segment"},
    {"node": "fsl-waf", "kind": "host", "alerts": [], "verdict": "blocked", "rules": ["920272", "949110"]},
    {"node": "estate", "kind": "segment"},
    {"node": "fsl-wg-board", "kind": "host", "status": None, "reached": False},
]

def serving(web_ui):
    return f"""
browser.serve((request) => {{
  if (request.route === "/api/topology/") return {{body: {{source: "gns3", status: "", detail: "",
    project: {js(PROJECT)}, web_ui: {js(web_ui)}}}}};
  if (request.route === "/api/sessions/1/topology/") return {{body: {{segments: [], project: {{nodes: {{
    "fsl-waf": {{status: "running", addresses: {{estate: ["172.30.0.3"]}}}},
    "fsl-kali": {{status: "not reported", addresses: {{}}}}}}}}}}}};
  if (request.route === "/api/sessions/1/site/requests/") return {{body: [
    {{id: 7, method: "GET", url: "http://board.com/search/?q=%ED%95%9C", status: 403, blocked: true}}]}};
  if (request.route === "/api/sessions/1/topology/follow/") return {{body: {{hops: {js(HOPS)}}}}};
  return {{status: 404, body: {{detail: "not served"}}}};
}});
"""

READ = """
return {
  frame: browser.element('topology-frame').getAttribute('src'),
  frameShown: browser.element('topology-frame').style.display,
  mapShown: browser.element('topology-map').style.display,
  said: browser.text('topology-said'),
  svg: browser.element('topology-svg').innerHTML,
  hops: browser.text('topology-hops'),
  follows: browser.requests.filter((r) => r.route.endsWith('/topology/follow/')).map((r) => r.query.request),
};
"""

def test_the_topology_pane_frames_the_gns3_web_ui_through_its_read_only_sign_in(client):
    web_ui = {"port": 3080, "path": "/static/web-ui/fsl-auditor.html?project=p"}
    seen = open_page(client, "/blue/1/", setup=serving(web_ui), scenario="""
      await browser.click('[data-pane="topology"]');
    """ + READ)

    assert seen["errors"] == []
    assert seen["result"]["frame"] == "http://console.test:3080/static/web-ui/fsl-auditor.html?project=p"
    assert seen["result"]["frameShown"] == "block" and seen["result"]["mapShown"] == "none"

def test_without_gns3_the_pane_draws_the_project_and_follows_a_chosen_request(client):
    seen = open_page(client, "/blue/1/", setup=serving(None), scenario="""
      await browser.click('[data-pane="topology"]');
      await browser.choose('topology-request', '7');
    """ + READ)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["frame"] is None and result["mapShown"] == "flex"
    assert result["said"] == english("topology.no_web_ui")
    assert result["follows"] == ["7"]
    assert 'data-node="fsl-wg-corp-db"' in result["svg"], "every node of the file is drawn"
    assert result["svg"].count('data-path="true"') == 3, "the three links the request crossed are marked"
    assert english("topology.hop.blocked", "920272, 949110") in result["hops"]
    assert english("topology.hop.not_reached") in result["hops"]
