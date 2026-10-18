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
    assert result["console"] == {"network": False, "blank": True, "selected": ["console"], "text": "top Default levels >"}
    assert "&lt;h1" in result["elements"] and "Board" in result["elements"] and "&lt;body" in result["elements"]
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

PLAIN = """
const plain = (row) => row.innerHTML.replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
"""

PAGE = """
const PAGE = `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Board</title>
  <!-- header -->
  <script>
    var a = 1;
    var b = 2;
  </script>
</head>
<body class="home dark">
  <div id="wrap">
    <h1>Board</h1>
    <ul><li>one</li><li>two</li></ul>
    <p>Hello<br>again</p>
  </div>
</body>
</html>`;
"""

def test_elements_is_a_collapsible_tree_coloured_as_chrome_colours_it(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS + PAGE + PLAIN, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      dev.rows = [doc];
      dev.documents[1] = {response_body: {text: PAGE, size: PAGE.length, truncated: false}};
      document.querySelector('[data-panel="elements"]').click();
      await browser.settle();
      const lines = () => [...document.querySelectorAll('#site-dev-dom [data-node]')].map(plain);
      const first = lines();
      const rows = () => document.querySelectorAll('#site-dev-dom [data-node]');
      const fold = (text) => rows().find((row) => plain(row).startsWith(text)).querySelector('[data-fold]');
      fold('\u25B6<head>').click();
      await browser.settle();
      const head = lines();
      fold('\u25B6<div').click();
      await browser.settle();
      const div = lines();
      fold('\\u25B6<p>').click();
      await browser.settle();
      const para = lines();
      const markup = browser.element('site-dev-dom').innerHTML;
      const crumbs = browser.text('site-dev-crumbs');
      fold('\u25BC<div').click();
      await browser.settle();
      return {first, head, div, para, crumbs, markup, again: lines()};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["first"] == [
        "<!DOCTYPE html>", '\u25BC<html lang="ko">', "\u25B6<head>\u2026</head>",
        '\u25BC<body class="home dark"> == $0', '\u25B6<div id="wrap">\u2026</div>', "</body>", "</html>",
    ]
    assert any(line.startswith("<meta charset=\"utf-8\">") for line in result["head"])
    assert "<title>Board</title>" in result["head"]
    assert "<!-- header -->" in result["head"]
    assert "<h1>Board</h1>" in result["div"] and "\u25B6<p>\u2026</p>" in result["div"]
    assert '"Hello"' in result["para"] and "<br>" in result["para"] and '"again"' in result["para"]
    assert any(line.startswith("\u25B6<ul>") for line in result["div"])
    assert '<span class="dv-tag">&lt;div</span> <span class="dv-an">id</span>=<span class="dv-av">"wrap"</span>' in result["markup"]
    assert result["crumbs"] == "html body.home.dark div#wrap p"
    assert not any("<h1>" in line for line in result["again"])

def test_elements_keeps_its_folds_when_new_requests_refill_the_panel(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS + PAGE + PLAIN, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      dev.rows = [doc];
      dev.documents[1] = {response_body: {text: PAGE, size: PAGE.length, truncated: false}};
      document.querySelector('[data-panel="elements"]').click();
      await browser.settle();
      const rows = () => [...document.querySelectorAll('#site-dev-dom [data-node]')];
      rows().find((row) => plain(row).startsWith('\u25B6<head>')).querySelector('[data-fold]').click();
      await browser.settle();
      dev.rows.push(css);
      await devFill('elements');
      const kept = rows().map(plain);
      dev.rows = [{...doc, id: 9}];
      dev.documents[9] = {response_body: {text: '<html><body><p>x</p></body></html>', size: 36, truncated: false}};
      await devFill('elements');
      return {kept, other: rows().map(plain)};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert any(line.startswith("\u25BC<head>") for line in result["kept"])
    assert result["other"] == ["\u25BC<html>", "\u25BC<body> == $0", "<p>x</p>", "</body>", "</html>"]

def test_an_empty_page_shows_the_bare_document_and_the_style_pane_shows_element_style(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS + PLAIN, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      document.querySelector('[data-panel="elements"]').click();
      await browser.settle();
      const tree = [...document.querySelectorAll('#site-dev-dom [data-node]')].map(plain);
      const side = [...document.querySelectorAll('#site-dev-side-tabs [data-side]')].map((tab) => tab.textContent);
      const styles = browser.text('site-dev-side-body');
      document.querySelector('[data-side="layout"]').click();
      return {tree, side, styles, layout: browser.text('site-dev-side-body'), filter: browser.element('site-dev-side-filter').style.display};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["tree"] == ["\u25BC<html>", "<head></head>", "<body></body> == $0", "</html>"]
    assert result["side"] == ["Styles", "Computed", "Layout", "Event Listeners"]
    assert result["styles"] == "element.style { }" and result["layout"] == "" and result["filter"] == "none"

def test_sources_has_the_page_navigator_with_the_site_folders_and_opens_the_chosen_file(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS + PAGE + PLAIN, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      dev.rows = [doc, css];
      dev.documents[1] = {response_body: {text: PAGE, size: PAGE.length, truncated: false}};
      dev.documents[2] = {response_body: {text: 'body { margin: 0 }', size: 18, truncated: false}};
      document.querySelector('[data-panel="sources"]').click();
      await browser.settle();
      const names = () => [...document.querySelectorAll('#site-dev-navbody .dv-navrow')].map(plain);
      const first = names();
      const tabs = [...document.querySelectorAll('[data-navtab]')].map((tab) => tab.textContent);
      const open = () => document.querySelector('.dv-main .dv-tab');
      const opened = open().textContent;
      document.querySelector('[data-folder="top/board.com/static"]').click();
      await browser.settle();
      const folder = names();
      document.querySelector('[data-source="http://board.com/static/app.css"]').click();
      await browser.settle();
      const code = browser.text('site-dev-code');
      const kept = names();
      document.querySelector('[data-folder="top/board.com/static"]').click();
      await browser.settle();
      const shut = names();
      const status = browser.element('site-dev-blank').querySelector('.dv-status').textContent;
      document.querySelector('[data-close="file"]').click();
      await browser.settle();
      const closed = browser.text('site-dev-code');
      document.querySelector('[data-navtab="overrides"]').click();
      await browser.settle();
      return {first, tabs, opened, folder, code, kept, shut, status, closed, overrides: browser.text('site-dev-navbody')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["first"] == ["\u25BCtop", "\u25BCboard.com", "\u25B6search", "\u25B6static"] or result["first"] == [
        "\u25BCtop", "\u25BCboard.com", "\u25BCsearch", "(index)?q=hello", "\u25B6static"]
    assert result["tabs"] == ["Page", "Workspace", "Overrides"]
    assert result["opened"].startswith("(index)?q=hello")
    assert "app.css" in result["folder"]
    assert "body { margin: 0 }" in result["code"]
    assert "app.css" in result["kept"] and "app.css" not in result["shut"]
    assert result["status"].startswith("Line 1, Column 1")
    assert result["closed"].startswith("Open file")
    assert result["overrides"] == "No local overrides set"

def test_the_console_has_chromes_toolbar_above_the_prompt(client):
    seen = open_page(client, "/blue/1/", setup=served() + ROWS, scenario="""
      await browser.click('[data-pane="site"]');
      await browser.click('site-dev-toggle');
      document.querySelector('[data-panel="console"]').click();
      await browser.settle();
      const blank = browser.element('site-dev-blank');
      return {
        titles: [...blank.querySelectorAll('button')].map((button) => button.title),
        selects: [...blank.querySelectorAll('select')].map((select) => select.textContent),
        filter: blank.querySelector('input').placeholder,
        order: [...blank.querySelectorAll('.dv-bar, .dv-prompt')].map((box) => box.className.split(' ')[0]),
      };
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["titles"] == ["Show console sidebar", "Clear console", "Create live expression", "Console settings"]
    assert result["selects"] == ["top", "Default levels"]
    assert result["filter"] == "Filter"
    assert result["order"] == ["dv-bar", "dv-prompt"]
