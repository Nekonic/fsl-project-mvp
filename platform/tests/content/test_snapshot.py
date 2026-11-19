import json

from content import service
from testing import factories


def stored(as_staff, document):
    answer = as_staff.post("/api/staff/problems/", document, format="json")
    assert answer.status_code == 201, answer.content
    return answer.json()["problem"]["id"]


def test_a_snapshot_freezes_the_problem_with_its_revision_posture_and_benign_cases(source, as_staff):
    problem_id = stored(as_staff, factories.round_problem(probe_cases=["board-sqli-search"]))

    frozen = service.snapshot(service.problem(problem_id))

    assert frozen["problem"]["revision"] == 1
    assert frozen["wargame"]["public_url"] == "http://board.com"
    assert frozen["round"]["posture"] == {"name": "placeholder start", "suricata_rules": "",
                                          "crs_tuning": {"paranoia": 2, "exclusions": []}}
    assert frozen["round"]["traffic"] == "community"
    assert frozen["round"]["probe_cases"] == ["board-sqli-search"]
    assert "board-normal-search-with-apostrophe" in frozen["round"]["benign_cases"]
    assert not any(name.startswith("board-sqli") for name in frozen["round"]["benign_cases"])
    assert [tier["key"] for tier in frozen["objectives"]] == ["board-auth-user-admin"]
    assert json.loads(json.dumps(frozen)) == frozen


def test_a_staff_edit_after_the_snapshot_leaves_the_snapshot_unchanged(source, as_staff):
    problem_id = stored(as_staff, factories.lesson())
    frozen = service.snapshot(service.problem(problem_id))
    kept = json.dumps(frozen, sort_keys=True)

    edited = factories.lesson(title="Edited mid-round")
    edited["steps"][0]["check"]["params"]["accept"] = ["another answer"]
    edited["start_posture"]["crs_tuning"] = {"paranoia": 4}
    as_staff.put(f"/api/staff/problems/{problem_id}/", {**edited, "base_revision": 1}, format="json")

    assert json.dumps(frozen, sort_keys=True) == kept
    later = service.snapshot(service.problem(problem_id))
    assert later["problem"]["revision"] == 2 and later["problem"]["title"] == "Edited mid-round"
    assert frozen["steps"][0]["check"]["params"]["accept"] == ["placeholder answer"]


def test_a_lesson_snapshot_carries_its_steps_with_their_checks(source, as_staff):
    frozen = service.snapshot(service.problem(stored(as_staff, factories.lesson())))

    assert frozen["round"] is None
    assert [step["check"]["kind"] for step in frozen["steps"]] == ["answer", "choice", "rule_test"]
    assert frozen["start_posture"]["name"] == "placeholder start"
    assert len(frozen["objectives"]) == 3
