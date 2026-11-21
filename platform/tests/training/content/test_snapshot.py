import json

from testing import factories
from training.content import problems as service


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
    problem_id = stored(as_staff, factories.round_problem())
    frozen = service.snapshot(service.problem(problem_id))
    kept = json.dumps(frozen, sort_keys=True)

    edited = factories.round_problem({"title": "Edited mid-round"}, time_limit_s=60)
    edited["start_posture"]["crs_tuning"] = {"paranoia": 4}
    as_staff.put(f"/api/staff/problems/{problem_id}/", {**edited, "base_revision": 1}, format="json")

    assert json.dumps(frozen, sort_keys=True) == kept
    later = service.snapshot(service.problem(problem_id))
    assert later["problem"]["revision"] == 2 and later["problem"]["title"] == "Edited mid-round"
    assert frozen["round"]["time_limit_s"] == 900
