import pytest
import yaml

from cr.config import WafConfig
from tests.shape import refused
from tests.training.content.conftest import RECORDED, REPO
from training.content import catalog


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


def test_the_limit_req_floor_is_twice_the_busiest_board_customer_origin_and_corp_has_no_customers():
    board, corp = catalog.wargames(REPO)

    assert (board.limit_floor_rpm, corp.limit_floor_rpm) == (90, None), (
        "nine of the board's twelve customers come from kr at one request a second between them")


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
                         "default_traffic": "community", "waf_files": list(WafConfig().files)}


def test_a_learner_is_refused_the_wargame_list(source, as_learner):
    refused(as_learner.get("/api/staff/wargames/"), 403, "not_staff")


def test_a_broken_catalog_is_a_server_fault_not_the_staff_member_s(source, as_staff):
    (source / "wargames" / "board" / "probes" / "manifest.json").write_text("{}")

    refused(as_staff.get("/api/staff/wargames/"), 500, "server_error")


def test_an_objective_tier_without_a_key_is_refused_by_name(source):
    path = source / "wargames" / "board" / "objectives.yaml"
    declared = yaml.safe_load(path.read_text())
    del declared["tiers"][0]["key"]
    path.write_text(yaml.safe_dump(declared, allow_unicode=True))

    with pytest.raises(catalog.CatalogBroken, match="malformed tier"):
        catalog.read(source, "board")


def test_each_tier_keeps_the_rule_the_target_judges_it_by_and_the_secret_names_its_role(source):
    board, corp = catalog.read(source, "board"), catalog.read(source, "corp")

    assert {tier.key: tier.rule for tier in board.objectives}["board-auth-user-admin"] == {"account": "admin"}
    assert {tier.key: tier.rule for tier in corp.objectives}["corp-rogue-admin"] == {"effect": "rogue_admin"}
    assert (board.secret["role"], board.secret["read_path"]) == ("board", "/internal/auth-users")
    assert corp.secret["role"] == "corp-db"


def test_a_secret_without_the_role_that_holds_it_is_refused(source):
    path = source / "wargames" / "board" / "objectives.yaml"
    declared = yaml.safe_load(path.read_text())
    del declared["secret"]["role"]
    path.write_text(yaml.safe_dump(declared, allow_unicode=True))

    with pytest.raises(catalog.CatalogBroken, match="role"):
        catalog.read(source, "board")
