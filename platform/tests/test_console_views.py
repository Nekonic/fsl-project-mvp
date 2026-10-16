import pathlib
import re

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

PAGES = ["/", "/session/1/", "/red/1/", "/blue/1/"]

@pytest.fixture
def client():
    return Client()

def test_pages_do_not_query_the_database(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        for path in PAGES:
            client.get(path)

    assert len(queries) == 0


CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"

TEMPLATES = sorted(path.name for path in CONSOLE.glob("*.html") if path.name != "strings.html")

def body(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return response.content.decode()

@pytest.mark.parametrize("name", sorted(path.name for path in CONSOLE.glob("*.html")))
def test_no_template_carries_a_comment(name):
    source = (CONSOLE / name).read_text()

    assert "{#" not in source and "<!--" not in source, name

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

@pytest.mark.parametrize("name", [name for name in TEMPLATES if name.startswith(("blue", "red", "main"))])
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
def test_every_element_the_script_reaches_for_is_on_the_page(client, path):
    page = body(client, path)
    reached_for = set(re.findall(r'getElementById\("([^"]+)"\)', page))
    present = set(re.findall(r'\bid="([^"]+)"', page))

    assert reached_for <= present, (
        f"{path}: the script reaches for {sorted(reached_for - present)}, "
        f"which is not on the page"
    )
