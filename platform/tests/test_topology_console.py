import pytest

from tests.browser import open_page

pytestmark = pytest.mark.django_db

SERVING = """
browser.serve((request) => ({status: 404, body: {detail: "not served"}}));
const shown = (id) => !browser.element(id).classList.contains('hidden');
"""


def test_the_topology_pane_frames_its_own_session_s_map_on_the_platform_s_own_origin(client):
    seen = open_page(client, "/blue/1/", setup=SERVING, scenario="""
      await browser.click('[data-pane="topology"]');
      return {frame: browser.element('topology-frame').getAttribute('src'),
              shown: browser.element('topology-frame').style.display,
              asked: browser.requests.map((r) => r.route).filter((route) => /topology|3080/.test(route))};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"frame": "/map/1/", "shown": "block", "asked": []}


def test_the_map_pane_says_it_is_loading_until_the_map_says_it_is_drawn(client):
    seen = open_page(client, "/blue/1/", setup=SERVING, scenario="""
      await browser.click('[data-pane="topology"]');
      const asked = shown('map-wait');
      await browser.click('[data-pane="elk"]');
      await browser.click('[data-pane="topology"]');
      return {asked, still: shown('map-wait'), frame: browser.element('topology-frame').getAttribute('src')};
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"asked": True, "still": True, "frame": "/map/1/"}
