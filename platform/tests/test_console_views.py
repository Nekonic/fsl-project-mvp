import pathlib
import re

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/", "/board/1/"]


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


# -- two distances, two windows -------------------------------------------
# A monitoring console is watched from two distances and they are not the same
# screen. The board is the ten-foot view: counts, a map, a trend, the shape of
# the range - read from across a room, with nothing on it to operate. The
# alert list is the three-foot view: filters, a table, and the whole log
# record behind a row. Putting both in one window is what this split.

# The board's widgets are tables, the way real ones are: a summary, a trend,
# and top-N by a dimension. Cloudflare's security events screen is counters,
# one time series and "top events by source"; Igloo's write-up adds the column
# that makes an address mean something - what it belongs to.
BOARD_ONLY = ['id="kpi-total"', 'id="map-points"', 'id="sources"',
              'id="destinations"', 'id="signatures"', 'id="paths"']
LIST_ONLY = ['id="rows"', 'id="search"', 'id="only-orphans"', 'id="source-filter"']


def body(client, path):
    return client.get(path).content.decode()


def test_the_board_carries_what_is_read_from_across_a_room(client):
    page = body(client, "/board/1/")

    for marker in BOARD_ONLY:
        assert marker in page, marker


def test_the_board_has_nothing_on_it_to_operate(client):
    # Filters and a table cannot be read at a distance or worked by someone
    # who is not sitting in front of them, which is the whole distinction.
    page = body(client, "/board/1/")

    for marker in LIST_ONLY:
        assert marker not in page, f"the board carries {marker}"


def test_the_board_says_nothing_about_how_the_range_is_built(client):
    # Which container bridges which network, and which segment has no sensor,
    # are findings about the stack. They belong in DECISIONS and in a test; a
    # room watching traffic has no use for them, and they were on here in
    # words nobody outside this repo could read.
    page = body(client, "/board/1/")

    for invented in ("ways in", "unwatched", "fsl-", "crosses"):
        assert invented not in page, invented


def test_the_board_reports_each_dimension_as_a_table(client):
    # A bar chart of eight addresses says less than eight rows naming them,
    # what they belong to and where they are - and a room reads a table from
    # further away than it reads a diagram.
    page = body(client, "/board/1/")

    for column in ("Source IP", "Zone", "Country", "Events", "Destination",
                   "Signature", "Engine", "Method", "Path"):
        assert f">{column}<" in page, column


def test_the_alert_list_says_what_each_address_belongs_to(client):
    # The defect Igloo names: the device that raised an alert is obvious from
    # the alert, but what the source address belongs to is not, and an analyst
    # reading bare addresses does that lookup in their head.
    page = body(client, "/blue/1/")

    assert ">Zone<" in page and ">Country<" in page
    assert "/top/" in page


def test_the_alert_list_is_the_alert_list(client):
    page = body(client, "/blue/1/")

    for marker in LIST_ONLY:
        assert marker in page, marker
    for marker in BOARD_ONLY:
        assert marker not in page, f"the alert list carries {marker}"


def test_the_console_fills_the_screen_rather_than_scrolling_as_a_page(client):
    for path in ("/blue/1/", "/board/1/"):
        assert "h-screen" in body(client, path), path
        assert "overflow-hidden" in body(client, path), path


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


@pytest.mark.parametrize("name", ["blue.html", "board.html", "red.html"])
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
