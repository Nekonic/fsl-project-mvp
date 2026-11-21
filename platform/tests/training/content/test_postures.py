import pytest

from testing import factories
from tests.shape import refused


@pytest.fixture
def made(source, as_staff):
    answer = as_staff.post("/api/staff/postures/", factories.posture(), format="json")
    assert answer.status_code == 201, answer.content
    return answer.json()


def test_a_posture_is_stored_with_its_tuning_normalised(made, as_staff):
    assert made["crs_tuning"] == {"paranoia": 2, "exclusions": []}
    assert as_staff.get(f"/api/staff/postures/{made['id']}/").json() == made
    assert as_staff.get("/api/staff/postures/").json() == [made]


def test_a_posture_is_updated_in_place(made, as_staff):
    changed = factories.posture(suricata_rules="alert http any any -> any any (sid:1;)",
                                crs_tuning={"paranoia": 3, "detection_only": True})

    answer = as_staff.put(f"/api/staff/postures/{made['id']}/", changed, format="json").json()

    assert answer["id"] == made["id"]
    assert answer["crs_tuning"] == {"paranoia": 3, "exclusions": [], "detection_only": True}


@pytest.mark.parametrize("fields, path, code", [
    ({"crs_tuning": {"paranoia": 2, "exclusions": [{"rule_id": 5}]}}, "crs_tuning", "crs_refused"),
    ({"wargame": "bank"}, "wargame", "unknown_wargame"),
    ({"name": " "}, "name", "required"),
    ({"suricata_rules": 7}, "suricata_rules", "not_a_text"),
    ({"engine": "ids"}, "engine", "unknown_field"),
])
def test_a_wrong_posture_is_refused_by_path(source, as_staff, fields, path, code):
    refused(as_staff.post("/api/staff/postures/", factories.posture(**fields), format="json"), 400, code, path)


def test_two_postures_of_one_wargame_cannot_share_a_name(made, as_staff):
    refused(as_staff.post("/api/staff/postures/", factories.posture(), format="json"), 400, "name_taken", "name")

    assert as_staff.post("/api/staff/postures/", factories.posture(wargame="corp"), format="json").status_code == 201


def test_an_unknown_posture_is_not_found(source, as_staff):
    refused(as_staff.get("/api/staff/postures/999/"), 404, "unknown_posture")


def test_a_problem_s_round_may_name_a_posture_staff_made_first(made, as_staff):
    document = factories.round_problem(posture="placeholder posture")

    answer = as_staff.post("/api/staff/problems/", document, format="json")

    assert answer.status_code == 201, answer.content
    assert answer.json()["round"]["posture"] == "placeholder posture"


def test_a_learner_is_refused_the_posture_routes(source, as_learner):
    refused(as_learner.get("/api/staff/postures/"), 403, "not_staff")
    refused(as_learner.post("/api/staff/postures/", factories.posture(), format="json"), 403, "not_staff")
