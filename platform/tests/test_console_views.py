import pathlib
import re

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/"]

@pytest.fixture
def client():
    return Client()

@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)

    assert response.status_code == 200

@pytest.mark.parametrize("path", PAGES)
def test_page_fetches_its_data_from_the_api(client, path):
                                                                           
                                                                                   
    body = client.get(path).content.decode()

    assert "/api/" in body
    assert "fetch(" in body

def test_pages_do_not_query_the_database(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        for path in PAGES:
            client.get(path)

    assert len(queries) == 0

                                                                              
                                                                              
                                                                           
                                                                             
                                                                             
                                      

OVERVIEW = ['id="kpi-total"', 'id="map-points"', 'id="sources"',
            'id="destinations"', 'id="signatures"', 'id="paths"']
THE_LIST = ['id="rows"', 'id="search"', 'id="only-orphans"', 'id="source-filter"']

def body(client, path):
    return client.get(path).content.decode()

def test_the_blue_console_carries_both_views(client):
    page = body(client, "/blue/1/")

    for marker in OVERVIEW + THE_LIST:
        assert marker in page, marker

def test_the_two_views_are_tabs_rather_than_one_screenful(client):
                                                                             
                                                                   
    page = body(client, "/blue/1/")

    for tab in ("dashboard", "alerts", "score", "rules"):
        assert f'data-tab="{tab}"' in page, tab
        assert f'data-panel="{tab}"' in page or tab == "alerts", tab

def test_the_overview_reports_each_dimension_as_a_table(client):
    page = body(client, "/blue/1/")

    for column in ("Source IP", "Zone", "Country", "Events", "Destination",
                   "Signature", "Engine", "Method", "Path"):
        assert f">{column}<" in page, column

def test_the_overview_says_nothing_about_how_the_range_is_built(client):
                                                                             
                                                                             
    page = body(client, "/blue/1/")

    for invented in ("ways in", "unwatched", "crosses"):
        assert invented not in page, invented

def test_there_is_no_second_address_for_the_same_console(client):
    assert client.get("/board/1/").status_code == 404

def test_the_console_fills_the_screen_rather_than_scrolling_as_a_page(client):
    page = body(client, "/blue/1/")

    assert "h-screen" in page and "overflow-hidden" in page

def test_a_template_comment_never_reaches_the_browser(client):
                                                                              
                                                                         
    for path in PAGES:
        page = body(client, path)
        assert "{#" not in page and "#}" not in page, path

                                                                            
                                                                             
                                                                          
                                                                             
                                                                              
                                                                            
                                                 

CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"

                                                                             
                                                     
UNTRUSTED = (
    ".signature", ".path", ".description", ".reason", ".src_ip", ".dest",
    ".marker", ".zone", ".country", ".city", ".summary", ".takes", ".detail",
    ".subnet", ".label", ".category", "decodePath(",
)

def interpolations(source):
    for match in re.finditer(r"\$\{", source):
        depth, i = 1, match.end()
        while i < len(source) and depth:
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            i += 1

        opened = source.rfind("`", 0, match.start())
        closed = source.find("`", i)
        if opened < 0 or closed < 0 or "<" not in source[opened:closed]:
            continue

        yield source.count("\n", 0, match.start()), source[match.end():i - 1]

@pytest.mark.parametrize("name", ["blue.html", "red.html"])
def test_no_untrusted_value_is_written_into_markup_unescaped(name):
    source = (CONSOLE / name).read_text()
    offenders = []

    for line, expression in interpolations(source):
        if "esc(" in expression:
            continue
                                                                          
                                                             
        emitted = expression.split("?", 1)[1] if "?" in expression else expression
        if not any(field in emitted for field in UNTRUSTED):
            continue
        offenders.append(f"{name}:{line + 1}  ${{{expression.strip()[:70]}}}")

    assert not offenders, "unescaped into markup:\n" + "\n".join(offenders)

@pytest.mark.parametrize("path", PAGES)
def test_no_script_block_is_closed_early_by_its_own_text(client, path):
    body = client.get(path).content.decode()
    opened = body.count("<script")
    closed = body.count("</script>")

    assert opened == closed, (
        f"{path}: {opened} script elements opened, {closed} closed - "
        f"something wrote a closing tag where it is not one"
    )

@pytest.mark.parametrize("path", PAGES)
def test_every_element_the_script_reaches_for_is_on_the_page(client, path):
    page = body(client, path)
    reached_for = set(re.findall(r'getElementById\("([^"]+)"\)', page))
    present = set(re.findall(r'\bid="([^"]+)"', page))

    assert reached_for <= present, (
        f"{path}: the script reaches for {sorted(reached_for - present)}, "
        f"which is not on the page"
    )
