import json

import pytest
from rest_framework.test import APIClient

from testing import factories
from tests.shape import refused

WITHHELD = ("accept", "correct", "params", "placeholder answer", "first placeholder hint")


@pytest.fixture
def stored(source, as_staff):
    shown = as_staff.post("/api/staff/problems/", factories.lesson(), format="json").json()
    hidden = as_staff.post("/api/staff/problems/", factories.lesson(title="Unpublished", published=False),
                           format="json").json()
    return shown["problem"]["id"], hidden["problem"]["id"]


def test_a_learner_lists_only_published_problems(stored, as_learner):
    shown, _ = stored

    assert as_learner.get("/api/problems/").json() == [
        {"id": shown, "kind": "lesson", "wargame": "board", "side": "defence", "title": "Placeholder lesson",
         "summary": "Placeholder summary"}]


def test_a_learner_reads_a_published_problem_without_any_answer(stored, as_learner):
    shown, _ = stored

    answer = as_learner.get(f"/api/problems/{shown}/")
    body = answer.json()

    assert [step["kind"] for step in body["steps"]] == ["answer", "choice", "rule_test"]
    assert body["steps"][1]["options"] == ["left", "right"]
    assert body["steps"][0]["hints_available"] == 2 and body["steps"][0]["options"] == []
    assert set(body["steps"][0]) == {"order", "body", "opens", "kind", "options", "hints_available"}
    assert [word for word in WITHHELD if word in json.dumps(body)] == []


def test_an_unpublished_problem_is_unknown_to_a_learner(stored, as_learner):
    _, hidden = stored

    refused(as_learner.get(f"/api/problems/{hidden}/"), 404, "unknown_problem")


def test_a_stranger_cannot_read_the_catalog(stored):
    refused(APIClient().get("/api/problems/"), 401, "not_signed_in")
