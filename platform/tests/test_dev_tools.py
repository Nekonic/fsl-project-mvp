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
             size: 900, ms: 20, body_size: 3000};
const cached = {id: 3, at: NOW + 0.3, method: "GET", url: "http://board.com/static/app.css", status: 200, status_text: "OK",
                type: "stylesheet", category: "css", initiator: {type: "parser", url: "http://board.com/search/?q=hello"},
                size: 0, ms: 0, cache: "disk", body_size: 3000};
"""

def test_the_tools_open_on_the_network_panel_and_the_other_panels_show_what_chrome_shows(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      const panel = (name) => document.querySelector(`[data-panel="${name}"]`);
      const state = () => ({network: shown('site-dev-network'), blank: shown('site-dev-blank'),
                            selected: ['elements', 'console', 'sources', 'network'].filter((n) => panel(n).getAttribute('aria-selected') === 'true')});
      const opened = state();
      dev.rows = [doc];
      dev.documents[1] = {response_body: {text: '<html><body><h1>Board</h1><p>Hello</p></body></html>', size: 52, truncated: false}};
      panel('console').click();
      await browser.settle();
      const console = {...state(), text: browser.text('site-dev-blank')};
      panel('elements').click();
      await browser.settle();
      const elements = browser.element('site-dev-blank').innerHTML;
      panel('sources').click();
      await browser.settle();
      const sources = {...state(), text: browser.element('site-dev-blank').innerHTML};
      browser.element('site-dev-toggle').click();
      browser.element('site-dev-toggle').click();
      return {opened, console, elements, sources, reopened: state()};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["opened"] == {"network": True, "blank": False, "selected": ["network"]}
    assert result["console"] == {"network": False, "blank": True, "selected": ["console"], "text": ">"}
    assert "\n  &lt;body&gt;\n    &lt;h1&gt;Board&lt;/h1&gt;" in result["elements"]
    assert result["sources"]["blank"] and result["sources"]["selected"] == ["sources"]
    assert "&lt;h1&gt;Board&lt;/h1&gt;" in result["sources"]["text"] and "/site/" not in result["sources"]["text"]
    assert result["reopened"] == result["opened"], "the coach's rows and tabs are on screen whenever the tools open"

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
    assert "Total" in result["timing"] and "20 ms" in result["timing"]

def test_a_disk_cache_row_reads_as_in_chrome_and_the_resources_figure_is_the_decoded_size(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      dev.rows = [doc, css, cached];
      devRows();
      const cells = (index) => [...document.querySelectorAll('#site-dev-rows tr')[index].querySelectorAll('td')].map((cell) => cell.textContent);
      return {cached: cells(2), fetched: cells(1), resources: browser.text('site-dev-resources'), transferred: browser.text('site-dev-transferred')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["cached"][4:6] == ["(disk cache)", "0 ms"]
    assert result["fetched"][4] != "(disk cache)"
    assert result["resources"].startswith("10.2") and result["transferred"].startswith("5.1")

def test_the_last_waterfall_bar_ends_inside_the_column_and_no_bar_is_a_sliver(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      dev.rows = [doc, css, cached];
      devRows();
      const bars = document.querySelectorAll('#site-dev-rows .dv-wf i').map((bar) => bar.getAttribute('style'));
      const left = (style) => Number(/left: ([\\d.]+)%/.exec(style)[1]);
      const width = (style) => Number(/width: ([\\d.]+)%/.exec(style)[1]);
      return {ends: bars.map((style) => left(style) + width(style)), cachedLeft: left(bars[2])};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert max(result["ends"]) < 100
    assert result["cachedLeft"] < 100 and result["cachedLeft"] > 90

def test_the_type_chips_are_the_ones_chrome_shows_in_its_order(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      return [...document.querySelectorAll('#site-dev-types [data-type]')].map((chip) => chip.dataset.type);
    """)

    assert seen["errors"] == []
    assert seen["result"] == ["all", "xhr", "doc", "css", "js", "font", "img", "media", "manifest", "ws", "wasm", "other"]
