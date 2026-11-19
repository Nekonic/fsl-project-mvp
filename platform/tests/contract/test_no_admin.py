from pathlib import Path

from django.conf import settings
from django.urls import get_resolver

from tests.shape import refused

PLATFORM = Path(__file__).resolve().parents[2]
NOT_INSTALLED = ("django.contrib.admin", "rest_framework.authtoken")


def callbacks(patterns=None):
    for entry in patterns if patterns is not None else get_resolver().url_patterns:
        if hasattr(entry, "url_patterns"):
            yield from callbacks(entry.url_patterns)
        else:
            yield entry.callback


def test_neither_django_admin_nor_drf_tokens_are_installed():
    assert [app for app in settings.INSTALLED_APPS if app.startswith(NOT_INSTALLED)] == []


def test_no_url_routes_to_an_admin_view():
    owners = {getattr(view, "__module__", "") for view in callbacks()}

    assert [owner for owner in owners if owner.startswith("django.contrib.admin")] == []


def test_the_admin_path_is_just_not_found(browser):
    refused(browser.get("/admin/"), 404, "not_found")


def test_no_platform_module_names_the_admin():
    naming = [str(path.relative_to(PLATFORM)) for path in PLATFORM.rglob("*.py")
              if ".venv" not in path.parts and "tests" not in path.parts
              and "django.contrib.admin" in path.read_text()]

    assert naming == []
