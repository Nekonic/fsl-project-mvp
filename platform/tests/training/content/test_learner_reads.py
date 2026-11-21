import pytest
from rest_framework.test import APIClient

from testing import factories
from tests.shape import refused


@pytest.fixture
def stored(source, as_staff):
    shown = as_staff.post("/api/staff/problems/", factories.round_problem({"published": True}), format="json").json()
    hidden = as_staff.post("/api/staff/problems/", factories.round_problem({"title": "Unpublished"}),
                           format="json").json()
    return shown["problem"]["id"], hidden["problem"]["id"]


def test_a_learner_lists_only_published_problems(stored, as_learner):
    shown, _ = stored

    assert as_learner.get("/api/problems/").json() == [
        {"id": shown, "kind": "round", "wargame": "board", "side": "defence", "title": "Placeholder round",
         "summary": "Placeholder summary"}]


def test_a_learner_reads_a_published_problem_without_its_setup(stored, as_learner):
    shown, _ = stored

    body = as_learner.get(f"/api/problems/{shown}/").json()

    assert set(body) == {"id", "kind", "wargame", "side", "title", "summary", "body"}


def test_an_unpublished_problem_is_unknown_to_a_learner(stored, as_learner):
    _, hidden = stored

    refused(as_learner.get(f"/api/problems/{hidden}/"), 404, "unknown_problem")


def test_a_stranger_cannot_read_the_catalog(stored):
    refused(APIClient().get("/api/problems/"), 401, "not_signed_in")
