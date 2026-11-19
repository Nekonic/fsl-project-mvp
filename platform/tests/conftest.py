import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

PASSWORD = "plain-placeholder-41"
CALLER = "203.0.113.7"


@pytest.fixture
def forget_counts():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def browser(db, forget_counts):
    from rest_framework.test import APIClient

    return APIClient(REMOTE_ADDR=CALLER)


@pytest.fixture
def make_user(db):
    from django.contrib.auth import get_user_model

    def made(username: str, *, staff: bool = False, active: bool = True):
        return get_user_model().objects.create_user(username=username, password=PASSWORD, is_staff=staff,
                                                    is_active=active)

    return made


@pytest.fixture
def staff(make_user):
    return make_user("operator", staff=True)


@pytest.fixture
def learner(make_user):
    return make_user("learner")


@pytest.fixture
def as_staff(browser, staff):
    browser.force_authenticate(staff)
    return browser


@pytest.fixture
def as_learner(browser, learner):
    browser.force_authenticate(learner)
    return browser
