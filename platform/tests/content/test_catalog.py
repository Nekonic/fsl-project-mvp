import pytest
import yaml

from content import catalog
from tests.content.conftest import REPO, RECORDED
from tests.shape import refused


def test_every_wargame_folder_declares_its_wargame_yaml():
    folders = sorted(path.name for path in (REPO / "wargames").iterdir() if (path / "topology.yaml").is_file())

    assert catalog.wargame_ids(REPO) == folders == ["board", "corp"]


def test_the_catalog_reads_board_and_corp_from_the_repo():
    board, corp = catalog.wargames(REPO)

    assert (board.id, board.objective_model, board.case_file, board.default_traffic) == (
        "board", "loot_verified", "board.yaml", "community")
    assert (corp.id, corp.objective_model, corp.case_file, corp.default_traffic) == (
        "corp", "effect_observed", "corp.yaml", None)
    assert board.hosts == ("board.com",) and corp.hosts == ("corp.com",)
    assert {"board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"} == {
        objective.key for objective in board.objectives}
    assert board.case("board-sqli-orderby-sqlmap").kind == "tool"
    assert board.case("board-sqli-search").malicious is True


@pytest.mark.parametrize("wargame_id", ["board", "corp"])
def test_every_wargame_keeps_benign_cases_and_probes_only_http_ones(wargame_id):
    wargame = catalog.read(REPO, wargame_id)

    assert wargame.benign_cases
    assert all(not wargame.case(name).malicious and not wargame.case(name).tool_case
               for name in wargame.benign_cases)


def test_the_probe_manifest_marks_its_cases_recorded(source):
    board = catalog.read(source, "board")
    checked = board.for_validation()

    assert board.recorded == frozenset(RECORDED)
    assert checked.cases["board-sqli-search"].recorded is True
    assert checked.cases["board-sqli-union-search"].recorded is False
    assert catalog.read(source, "corp").recorded == frozenset()


def rewritten(source, wargame_id, **fields):
    path = source / "wargames" / wargame_id / "wargame.yaml"
    declared = yaml.safe_load(path.read_text())
    declared.update(fields)
    path.write_text(yaml.safe_dump(declared))


@pytest.mark.parametrize("fields, said", [
    ({"id": "other"}, "names id"),
    ({"hosts": ["elsewhere.com"]}, "not all served"),
    ({"default_traffic": "crowd"}, "not a profile"),
    ({"objective_model": "guessed"}, "objective_model"),
    ({"case_file": "missing.yaml"}, "missing"),
])
def test_a_broken_wargame_yaml_is_refused_by_name(source, fields, said):
    rewritten(source, "board", **fields)

    with pytest.raises(catalog.CatalogBroken, match=said):
        catalog.read(source, "board")


def test_a_case_file_without_a_benign_case_is_refused(source):
    path = source / "redteam" / "cases" / "corp.yaml"
    path.write_text(yaml.safe_dump([case for case in yaml.safe_load(path.read_text()) if case["malicious"]]))

    with pytest.raises(catalog.CatalogBroken, match="no benign case"):
        catalog.read(source, "corp")


def test_a_missing_field_is_named(source):
    path = source / "wargames" / "corp" / "wargame.yaml"
    declared = yaml.safe_load(path.read_text())
    del declared["image"]
    path.write_text(yaml.safe_dump(declared))

    with pytest.raises(catalog.CatalogBroken, match="lacks image"):
        catalog.read(source, "corp")


def test_staff_read_the_wargames_synced_from_the_catalog(source, as_staff):
    listed = as_staff.get("/api/staff/wargames/").json()

    assert [wargame["id"] for wargame in listed] == ["board", "corp"]
    assert listed[0] == {"id": "board", "title": "Community board", "image": "ghcr.io/nekonic/cr-board",
                         "public_url": "http://board.com", "hosts": ["board.com"],
                         "objective_model": "loot_verified", "case_file": "board.yaml",
                         "default_traffic": "community"}


def test_a_learner_is_refused_the_wargame_list(source, as_learner):
    refused(as_learner.get("/api/staff/wargames/"), 403, "not_staff")
