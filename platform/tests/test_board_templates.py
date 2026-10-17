import json
import subprocess
import sys
from pathlib import Path

BOARD = Path(__file__).resolve().parents[2] / "wargames" / "board" / "app"

RENDER = """
import json, sys
sys.path.insert(0, sys.argv[1])
from django.conf import settings
settings.configure(
    INSTALLED_APPS=["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
                    "django.contrib.sessions", "django.contrib.messages", "posts"],
    ROOT_URLCONF="board.urls", STATIC_URL="static/", DATABASES={},
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}],
)
import django
django.setup()
from django.template.loader import render_to_string
from django.test import RequestFactory
pages = {}
for query in json.loads(sys.argv[2]):
    request = RequestFactory().get("/" + query)
    pages[query] = render_to_string("posts/post_list.html", {"posts": [], "request": request})
print(json.dumps(pages))
"""


def rendered(*queries):
    done = subprocess.run([sys.executable, "-c", RENDER, str(BOARD), json.dumps(queries)],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def selected(page):
    return [line.split('value="')[1].split('"')[0] for line in page.splitlines()
            if "<option" in line and " selected" in line]


def test_the_post_list_offers_an_ordinary_sort_control_over_the_sort_parameter_it_already_takes():
    pages = rendered("", "?sort=created_at", "?sort=title", "?sort=posts_post.id")
    page = pages[""]
    assert 'method="get"' in page and 'name="sort"' in page and 'onchange="this.form.submit()"' in page
    assert '<noscript><button' in page
    assert [line.split('value="')[1].split('"')[0] for line in page.splitlines() if "<option" in line] == [
        "-created_at", "created_at", "title"]
    assert selected(page) == ["-created_at"]
    assert selected(pages["?sort=created_at"]) == ["created_at"]
    assert selected(pages["?sort=title"]) == ["title"]
    assert selected(pages["?sort=posts_post.id"]) == []
    assert "posts_post.id" not in pages["?sort=posts_post.id"]
