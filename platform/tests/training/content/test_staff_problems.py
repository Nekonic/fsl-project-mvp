import pytest

from testing import factories
from tests import rounds
from tests.shape import refused
from training.models import Problem


@pytest.fixture
def saved(source, as_staff):
    answer = as_staff.post("/api/staff/problems/", factories.round_problem(), format="json")
    assert answer.status_code == 201, answer.content
    return answer.json()


def without_stamps(document):
    shown = {**document, "problem": dict(document["problem"])}
    for name in ("id", "revision", "author", "updated"):
        shown["problem"].pop(name, None)
    return shown


def test_a_new_problem_is_stored_whole_at_revision_one(saved, as_staff):
    stored = as_staff.get(f"/api/staff/problems/{saved['problem']['id']}/").json()

    assert stored == saved
    assert stored["problem"]["revision"] == 1 and stored["problem"]["author"] == "operator"
    assert stored["start_posture"] == {"name": "placeholder start", "suricata_rules": "",
                                       "waf_files": factories.WAF_FILES}
    assert without_stamps(stored) == factories.ROUND


def test_staff_list_problems_with_their_revision(saved, as_staff):
    listed = as_staff.get("/api/staff/problems/").json()

    assert [(row["id"], row["title"], row["revision"]) for row in listed] == [
        (saved["problem"]["id"], "Placeholder round", 1)]


def broken(edit):
    document = factories.round_problem()
    edit(document)
    return document


@pytest.mark.parametrize("edit, path, code", [
    (lambda doc: doc["problem"].update(wargame="bank"), "problem.wargame", "unknown_wargame"),
    (lambda doc: doc["start_posture"]["waf_files"].update({"/etc/nginx/nginx.conf": ""}),
     "start_posture.waf_files./etc/nginx/nginx.conf", "crs_refused"),
    (lambda doc: doc["start_posture"].update(crs_tuning={"paranoia": 2}), "start_posture.crs_tuning", "unknown_field"),
    (lambda doc: doc.update(notes={}), "notes", "unknown_field"),
    (lambda doc: doc["problem"].update(difficulty=3), "problem.difficulty", "unknown_field"),
    (lambda doc: doc["start_posture"].update(engine="ids"), "start_posture.engine", "unknown_field"),
])
def test_validator_errors_come_back_by_path_and_nothing_is_saved(source, as_staff, edit, path, code):
    refused(as_staff.post("/api/staff/problems/", broken(edit), format="json"), 400, code, path)

    assert Problem.objects.count() == 0


@pytest.mark.parametrize("setup, path, code", [
    ({"posture": "nowhere"}, "round.posture", "unknown_posture"),
    ({"traffic": "crowd"}, "round.traffic", "unknown_profile"),
    ({"matchups": ["atk_vs_bot"]}, "round.matchups[0]", "matchup_not_allowed"),
    ({"objectives": ["corp-rogue-admin"]}, "round.objectives[0]", "unknown_objective"),
    ({"probe_cases": ["board-sqli-union-search"]}, "round.probe_cases[0]", "not_recorded"),
    ({"probe_cases": ["board-normal-post-list"]}, "round.probe_cases[0]", "not_malicious"),
    ({"time_limit": 600}, "round.time_limit", "unknown_field"),
    ({"hp": {"budget": 100}}, "round.hp", "unknown_field"),
])
def test_round_setup_errors_come_back_by_path(source, as_staff, setup, path, code):
    refused(as_staff.post("/api/staff/problems/", factories.round_problem(**setup), format="json"), 400, code, path)


def test_a_round_problem_probes_recorded_attack_cases_and_names_its_posture(source, as_staff):
    answer = as_staff.post("/api/staff/problems/", factories.round_problem(probe_cases=["board-sqli-search"],
                                                                           traffic="plain"), format="json")

    assert answer.status_code == 201, answer.content
    assert answer.json()["round"] == {**factories.ROUND["round"], "probe_cases": ["board-sqli-search"],
                                           "traffic": "plain"}


def test_validate_reports_errors_by_path_without_saving(source, as_staff):
    found = as_staff.post("/api/staff/problems/validate/",
                          broken(lambda doc: doc["problem"].update(wargame="bank")), format="json").json()
    clean = as_staff.post("/api/staff/problems/validate/", factories.round_problem(), format="json").json()

    assert found == {"ok": False, "errors": [{"path": "problem.wargame", "code": "unknown_wargame"}]}
    assert clean == {"ok": True, "errors": []}
    assert Problem.objects.count() == 0


def test_a_put_on_the_current_revision_replaces_the_document_and_moves_the_revision(saved, as_staff):
    document = factories.round_problem({"title": "Placeholder round, edited"})

    answer = as_staff.put(f"/api/staff/problems/{saved['problem']['id']}/", {**document, "base_revision": 1},
                          format="json")

    assert answer.status_code == 200, answer.content
    assert answer.json()["problem"]["revision"] == 2
    assert answer.json()["problem"]["title"] == "Placeholder round, edited"


def test_a_put_on_a_stale_revision_is_refused_with_the_current_one(saved, as_staff):
    problem_id = saved["problem"]["id"]
    as_staff.put(f"/api/staff/problems/{problem_id}/", {**factories.round_problem(), "base_revision": 1}, format="json")

    found = refused(as_staff.put(f"/api/staff/problems/{problem_id}/",
                                 {**factories.round_problem({"title": "Late edit"}), "base_revision": 1}, format="json"),
                    409, "stale_revision")

    assert found["params"] == {"current_revision": 2}
    assert as_staff.get(f"/api/staff/problems/{problem_id}/").json()["problem"]["title"] == "Placeholder round"


def test_a_stored_document_read_back_is_accepted_as_the_next_put(saved, as_staff):
    problem_id = saved["problem"]["id"]

    answer = as_staff.put(f"/api/staff/problems/{problem_id}/", {**saved, "base_revision": 1}, format="json")

    assert answer.status_code == 200, answer.content
    assert answer.json()["problem"]["revision"] == 2


def test_a_put_without_a_base_revision_is_refused(saved, as_staff):
    refused(as_staff.put(f"/api/staff/problems/{saved['problem']['id']}/", factories.round_problem(), format="json"),
            400, "required", "base_revision")


def test_an_invalid_put_leaves_the_stored_document_and_revision_alone(saved, as_staff):
    problem_id = saved["problem"]["id"]
    document = factories.round_problem(objectives=["board-nothing"])

    refused(as_staff.put(f"/api/staff/problems/{problem_id}/", {**document, "base_revision": 1}, format="json"),
            400, "unknown_objective", "round.objectives[0]")

    assert as_staff.get(f"/api/staff/problems/{problem_id}/").json() == saved


def test_export_then_import_carries_the_same_document_into_a_new_problem(saved, as_staff):
    exported = as_staff.get(f"/api/staff/problems/{saved['problem']['id']}/export/").json()

    imported = as_staff.post("/api/staff/problems/import/", exported, format="json")

    assert "id" not in exported["problem"] and "revision" not in exported["problem"]
    assert exported == without_stamps(saved)
    assert imported.status_code == 201
    assert imported.json()["problem"]["id"] != saved["problem"]["id"]
    assert without_stamps(imported.json()) == exported


def test_an_import_is_validated_like_any_save(source, as_staff):
    refused(as_staff.post("/api/staff/problems/import/", broken(lambda doc: doc["problem"].update(side="red")),
                          format="json"), 400, "not_a_choice", "problem.side")


def test_a_problem_is_deleted_and_then_unknown(saved, as_staff):
    problem_id = saved["problem"]["id"]

    assert as_staff.delete(f"/api/staff/problems/{problem_id}/").status_code == 204
    refused(as_staff.get(f"/api/staff/problems/{problem_id}/"), 404, "unknown_problem")


def test_deleting_a_problem_a_round_still_holds_is_in_use(saved, as_staff):
    problem_id = saved["problem"]["id"]
    rounds.opened(Problem.objects.get(pk=problem_id))

    refused(as_staff.delete(f"/api/staff/problems/{problem_id}/"), 409, "in_use")

    assert Problem.objects.filter(pk=problem_id).exists()


def test_a_learner_is_refused_every_staff_problem_route(saved, as_learner):
    problem_id = saved["problem"]["id"]

    refused(as_learner.get("/api/staff/problems/"), 403, "not_staff")
    refused(as_learner.post("/api/staff/problems/", factories.round_problem(), format="json"), 403, "not_staff")
    refused(as_learner.get(f"/api/staff/problems/{problem_id}/export/"), 403, "not_staff")
    refused(as_learner.post("/api/staff/problems/validate/", factories.round_problem(), format="json"), 403, "not_staff")
