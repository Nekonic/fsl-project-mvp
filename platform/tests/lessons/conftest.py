import copy

import pytest

from content import service as content
from tests.conftest import CALLER
from tests.defence.conftest import copied_source, recorded
from tests.match.conftest import cloud
from testing import factories

SEARCH_RULE = 'alert http any any -> any any (msg:"SQL injection in search"; sid:1001; rev:1;)\n'
APPLY_STEP = {"order": 4, "body": "Placeholder step four", "opens": "waf",
              "check": {"kind": "rule_applied", "params": {"engine": "waf", "same_as_tested": False}}}

__all__ = ["cloud"]


@pytest.fixture
def source(tmp_path, settings):
    made = copied_source(tmp_path / "source")
    recorded(made)
    settings.CR_SOURCE = made
    return made


@pytest.fixture
def slot(source, cloud):
    made = cloud.in_slot(1)
    made.defence.node_runner("sensor").fires = {"board-sqli-search": {"1001": "SQL injection in search"}}
    return made


@pytest.fixture
def second_browser(db):
    from rest_framework.test import APIClient

    return APIClient(REMOTE_ADDR=CALLER)


@pytest.fixture
def problem(db):
    return content.save_document(factories.lesson(side="both"))


@pytest.fixture
def applying_problem(db):
    document = factories.lesson(side="both", title="Placeholder applying lesson")
    document["steps"].append(copy.deepcopy(APPLY_STEP))
    return content.save_document(document)


def opened(client, problem) -> dict:
    answer = client.post("/api/lessons/", {"problem": problem.pk}, format="json")
    assert answer.status_code == 201, answer.content
    return answer.json()


def checked(client, lesson: dict, order: int, answer=None):
    return client.post(f"/api/lessons/{lesson['round']}/steps/{order}/check/", {"answer": answer}, format="json")


def ran_rule_test(client, lesson: dict, text: str = SEARCH_RULE):
    answer = client.post(f"/api/rounds/{lesson['round']}/defence/ids/rules/test/", {"text": text}, format="json")
    assert answer.status_code == 200, answer.content
    return answer.json()
