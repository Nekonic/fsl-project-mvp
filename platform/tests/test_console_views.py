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
    # Structural rule: everything the UI does exists as a REST API first. A
    # template carrying server-rendered data would block an agent from taking over.
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


# -- one console, two views --------------------------------------------------
# A console is watched from two distances: an overview a room can read, and an
# analyst's list with filters and the record behind a row. They are tabs of
# one page rather than two addresses, so splitting them across screens is the
# operator's call - open this page twice and leave one on Dashboard - instead
# of a decision baked into the routes.

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
    # The distinction that matters is still there: only one of them is on the
    # screen at a time, which is what a grid of everything was not.
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
    # Which container bridges which network, and which segment has no sensor,
    # are findings about the stack. They belong in DECISIONS and in a test; a
    # room watching traffic has no use for them.
    page = body(client, "/blue/1/")

    for invented in ("ways in", "unwatched", "crosses"):
        assert invented not in page, invented


def test_there_is_no_second_address_for_the_same_console(client):
    assert client.get("/board/1/").status_code == 404


def test_the_console_fills_the_screen_rather_than_scrolling_as_a_page(client):
    page = body(client, "/blue/1/")

    assert "h-screen" in page and "overflow-hidden" in page


def test_a_template_comment_never_reaches_the_browser(client):
    # Django's {# #} is single-line only, so a multi-line one is not a comment
    # at all - it is rendered, and it was, across the top of the console.
    for path in PAGES:
        page = body(client, path)
        assert "{#" not in page and "#}" not in page, path


# -- the console must not run what it collected ----------------------------
# The range collects attacks and the console displays them, so the console is
# where a payload finally lands. `<script>alert(1)</script>` went out as a
# case, came back as a request path, and the board rendered it into innerHTML
# - a security tool executing the attack it caught. Juice Shop's own challenge
# text did it too: the DOM XSS challenge is *described* with an iframe whose
# src is javascript:, and the red window drew it.

CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"

# Values that reach a page from somewhere other than this repo: the attacker,
# the target, the logs, or a box the user typed into.
UNTRUSTED = (
    ".signature", ".path", ".description", ".reason", ".src_ip", ".dest",
    ".marker", ".zone", ".country", ".city", ".summary", ".takes", ".detail",
    ".subnet", ".label", ".category", "decodePath(",
)


def interpolations(source):
    """Every ${...} that is building markup, with the line it sits on.

    An interpolation inside a template literal with no tag in it is not
    markup - it is a message, and something like note() or textContent will
    put it on the screen as text. Escaping those would show &amp; to the user.
    """
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
        # A ternary that only picks between string literals never puts the
        # value on the page - it decides a CSS class from it.
        emitted = expression.split("?", 1)[1] if "?" in expression else expression
        if not any(field in emitted for field in UNTRUSTED):
            continue
        offenders.append(f"{name}:{line + 1}  ${{{expression.strip()[:70]}}}")

    assert not offenders, "unescaped into markup:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", PAGES)
def test_no_script_block_is_closed_early_by_its_own_text(client, path):
    """A closing script tag inside a comment or string ends the element.

    The HTML parser does not know it is inside a comment. Everything after it
    stops being JavaScript, so helpers defined below that point silently do
    not exist - which is exactly what a comment explaining XSS did here.
    """
    body = client.get(path).content.decode()
    opened = body.count("<script")
    closed = body.count("</script>")

    assert opened == closed, (
        f"{path}: {opened} script elements opened, {closed} closed - "
        f"something wrote a closing tag where it is not one"
    )


@pytest.mark.parametrize("path", PAGES)
def test_every_element_the_script_reaches_for_is_on_the_page(client, path):
    """A missing id is not a missing feature: it is a dead page.

    Removing the second console left behind one line setting the href of a
    link that no longer existed. `getElementById` returned null, assigning to
    it threw, and every statement after that line - including the one that
    picks which panel to show - never ran. The page rendered, with all four
    panels stacked on top of each other, and nothing said why.
    """
    page = body(client, path)
    reached_for = set(re.findall(r'getElementById\("([^"]+)"\)', page))
    present = set(re.findall(r'\bid="([^"]+)"', page))

    assert reached_for <= present, (
        f"{path}: the script reaches for {sorted(reached_for - present)}, "
        f"which is not on the page"
    )
