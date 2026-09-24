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
        assert f'data-panel="{tab}"' in page, tab

def test_the_overview_reports_each_dimension_as_a_table(client):
    page = body(client, "/blue/1/")
    english = strings()["en"]

    for key in ("blue.col.src_ip", "blue.col.zone", "blue.col.country",
                "blue.col.alerts", "blue.col.dest", "blue.col.signature",
                "blue.col.engine", "blue.col.method", "blue.col.path"):
        assert f'data-t="{key}"' in page, key
        assert english.get(key), key


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

def strings():
    from tests.test_strings import tables
    return tables()

TEMPLATES = ["base.html", "main.html", "session.html", "red.html", "blue.html"]

def test_a_rejected_fetch_comes_back_as_a_result_rather_than_a_throw():
    source = (CONSOLE / "base.html").read_text()
    helper = source[source.index("async function api("):]
    helper = helper[:helper.index("\n    }")]

    assert "try {" in helper and "catch" in helper, (
        "api() lets a rejected fetch escape, so every caller that destructures "
        "the result throws when a container is restarting"
    )
    assert "ok: false" in helper, (
        "api() must report the failure as a result rather than swallow it"
    )

@pytest.mark.parametrize("name", TEMPLATES)
def test_no_caller_reads_a_body_it_has_not_checked(name):
    source = (CONSOLE / name).read_text()
    offenders = [
        source.count("\n", 0, position) + 1
        for position in range(len(source))
        if source.startswith("const { body } = await api(", position)
    ]

    assert not offenders, (
        f"{name}:{offenders} destructures body without ok. With the stack down "
        "api() returns an error object, so body.map/slice/filter throws and the "
        "screen goes blank instead of saying what happened"
    )

def test_nothing_that_decides_a_recorded_address_can_move_while_recording():
    source = (CONSOLE / "red.html").read_text()
    lock = source[source.index("function lockCase("):]
    lock = lock[:lock.index("\n  }")]

    for control in ("window-name", "window-malicious", "window-route", "origin"):
        assert control in lock, (
            f"{control} stays live during a recording, and windowAddress() is read "
            "at stop time, so the case can be recorded against an address that "
            "never sent the traffic"
        )

def test_an_alert_the_operator_cannot_tune_says_why():
    source = (CONSOLE / "blue.html").read_text()
    drawer = source[source.index("async function openDrawer("):]
    drawer = drawer[:drawer.index("\n  }")]
    english = strings()["en"]

    assert "blue.drawer.not_tunable" in drawer, (
        "a ModSecurity alert carries a CRS rule id but no Suricata sid, so the "
        "whole verdict panel is hidden and the operator is told nothing about "
        "why this one cannot be silenced"
    )
    assert english.get("blue.drawer.not_tunable")

def test_the_drawer_names_the_rule_whichever_engine_raised_it():
    source = (CONSOLE / "blue.html").read_text()

    assert "details?.ruleId" in source or "details.ruleId" in source, (
        "ModSecurity puts its rule id in raw.details.ruleId; the drawer only "
        "looks for raw.alert.signature_id, so it shows the operator no rule "
        "number at all for half the engines"
    )

def test_the_console_tells_a_quiet_range_from_a_dead_one():
    source = (CONSOLE / "blue.html").read_text()
    paint = source[source.index("function paintLive("):]
    paint = paint[:paint.index("\n  }")]
    english = strings()["en"]

    assert "blue.live.unreachable" in paint, (
        "the blue console renders an empty range and a dead one identically"
    )
    assert "reachable" in english["blue.live.unreachable"].lower()
    assert "return" not in paint, (
        "paintLive must still report live and paused while unreachable, or the "
        "toggle gives no feedback at all when the stack is down"
    )


UNTRUSTED = (
    ".signature", ".path", ".description", ".reason", ".src_ip", ".dest",
    ".marker", ".zone", ".country", ".city", ".summary", ".takes", ".detail",
    ".subnet", ".label", ".category", ".scenario", ".host", "decodePath(",
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

@pytest.mark.parametrize("name", ["blue.html", "red.html", "main.html"])
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
