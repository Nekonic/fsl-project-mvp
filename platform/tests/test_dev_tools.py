import pytest

from tests.browser import open_page
from tests.test_lesson_console import served

pytestmark = pytest.mark.django_db

ROWS = """
const NOW = 1760000000;
const doc = {id: 1, at: NOW, method: "GET", url: "http://board.com/search/?q=hello", status: 200, status_text: "OK",
             type: "document", category: "doc", initiator: {type: "other"}, size: 4200, ms: 40};
const css = {id: 2, at: NOW + 0.2, method: "GET", url: "http://board.com/static/app.css", status: 200, status_text: "OK",
             type: "stylesheet", category: "css", initiator: {type: "parser", url: "http://board.com/search/?q=hello"},
             size: 900, ms: 20, resource_size: 3000};
"""

def test_the_tools_open_on_the_network_panel_and_the_other_panels_are_empty(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      const panel = (name) => document.querySelector(`[data-panel="${name}"]`);
      const state = () => ({network: shown('site-dev-network'), blank: shown('site-dev-blank'),
                            selected: ['elements', 'console', 'sources', 'network'].filter((n) => panel(n).getAttribute('aria-selected') === 'true')});
      const opened = state();
      panel('console').click();
      const console = state();
      panel('sources').click();
      const sources = state();
      browser.element('site-dev-toggle').click();
      browser.element('site-dev-toggle').click();
      return {opened, console, sources, reopened: state(), blankText: browser.text('site-dev-blank')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["opened"] == {"network": True, "blank": False, "selected": ["network"]}
    assert result["console"] == {"network": False, "blank": True, "selected": ["console"]}
    assert result["sources"] == {"network": False, "blank": True, "selected": ["sources"]}
    assert result["reopened"] == result["opened"], "the coach's rows and tabs are on screen whenever the tools open"
    assert result["blankText"] == "", "no made-up content in the panels the learner has nothing to inspect in"

def test_the_network_table_has_a_waterfall_bar_per_row_and_the_status_bar_sums_the_unpacked_sizes(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      dev.rows = [doc, css];
      devRows();
      const cells = document.querySelectorAll('#site-dev-rows tr').map((row) => row.querySelectorAll('td').length);
      const bars = document.querySelectorAll('#site-dev-rows .dv-wf i').map((bar) => bar.getAttribute('style'));
      return {cells, bars, resources: browser.text('site-dev-resources'), transferred: browser.text('site-dev-transferred')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["cells"] == [7, 7]
    assert len(result["bars"]) == 2 and result["bars"][0].startswith("left: 0.00%")
    assert result["resources"] != result["transferred"]

def test_the_initiator_and_timing_tabs_show_what_the_record_holds(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      dev.rows = [doc, css];
      const view = (record, tab) => {
        dev.record = record;
        dev.tab = tab;
        devShow();
        return browser.element('site-dev-view').innerHTML;
      };
      return {none: view(doc, 'initiator'), chain: view(css, 'initiator'), timing: view(css, 'timing')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert "No initiator data" in result["none"]
    assert "http://board.com/search/?q=hello" in result["chain"] and "http://board.com/static/app.css" in result["chain"]
    assert "Total" in result["timing"] and "20ms" in result["timing"]
