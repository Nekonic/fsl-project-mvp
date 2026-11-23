import shutil

from sandbox import crs, suricata
from tests.training.defence.conftest import LOGIN_RULE, SEARCH_RULE
from training.defence import rules as service

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"
DENY = "deny 203.0.113.9;\n"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def permits(runner, path):
    return [one.argv[-1] for one in runner.sent if one.argv[:3] == ["sh", "-c", crs.PERMIT] and one.argv[4] == path]


def test_a_waf_test_that_refuses_a_benign_case_does_not_pass(as_defender, board_round, cyber_range):
    cyber_range.gateway.blocks = {"probe-board-normal-search-with-apostrophe": "SQL Injection Attack"}

    result = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()

    assert result["ok"] is True and result["passed"] is False
    assert result["failed_benign"] == ["board-normal-search-with-apostrophe"]
    assert permits(cyber_range.gateway, "/var/lib/cr-reloaded/waf.passed") == []


def test_an_ids_test_that_alerts_on_a_benign_case_does_not_pass(as_defender, board_round, cyber_range):
    result = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").json()

    assert result["passed"] is False and result["failed_benign"] == ["board-normal-search-with-apostrophe"]
    assert permits(cyber_range.nodes["sensor"], "/var/lib/cr-reloaded/ids.passed") == []


def test_a_test_with_a_benign_case_left_unrecorded_does_not_pass(as_defender, board_round, cyber_range, source):
    shutil.rmtree(source / "wargames" / "board" / "probes")

    waf = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()
    ids = as_defender.post(url(board_round, "ids/rules/test/"), {"text": LOGIN_RULE}, format="json").json()

    assert waf["passed"] is False and ids["passed"] is False
    assert "board-normal-post-list" in waf["untested_benign"] and "board-normal-post-list" in ids["untested_benign"]
    assert permits(cyber_range.gateway, "/var/lib/cr-reloaded/waf.passed") == []
    assert permits(cyber_range.nodes["sensor"], "/var/lib/cr-reloaded/ids.passed") == []


def test_a_passing_test_lists_the_hash_the_reload_wrapper_computes_on_the_box(as_defender, board_round, cyber_range):
    waf = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()
    ids = as_defender.post(url(board_round, "ids/rules/test/"), {"text": LOGIN_RULE}, format="json").json()

    assert waf["passed"] is True and ids["passed"] is True
    assert permits(cyber_range.gateway, "/var/lib/cr-reloaded/waf.passed") == [
        crs.loaded_sha({**cyber_range.gateway.files, HTTP: DENY})]
    assert permits(cyber_range.nodes["sensor"], "/var/lib/cr-reloaded/ids.passed") == [suricata.loaded_sha(LOGIN_RULE)]


def test_the_console_applies_only_files_a_test_of_this_round_passed(as_defender, board_round, cyber_range):
    before = dict(cyber_range.gateway.files)
    untested = as_defender.post(url(board_round, "waf/apply/"), {"files": {HTTP: DENY}, "base_version": 0},
                                format="json")
    cyber_range.gateway.blocks = {"probe-board-normal-post-list": "refused"}
    as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json")
    failed = as_defender.post(url(board_round, "waf/apply/"), {"files": {HTTP: DENY}, "base_version": 0},
                              format="json")

    assert untested.status_code == failed.status_code == 409
    assert failed.json()["errors"] == [{"path": "files", "code": "not_tested"}]
    assert cyber_range.gateway.files == before
    assert service.versions(board_round, "waf") == []


def test_the_round_setup_clears_the_passed_tests_on_both_boxes(board_round, cyber_range):
    service.apply_posture(board_round)

    assert ["sh", "-c", crs.FORGET, "sh", "/var/lib/cr-reloaded/waf.passed"] in [
        one.argv for one in cyber_range.gateway.sent]
    assert ["sh", "-c", suricata.FORGET, "sh", "/var/lib/cr-reloaded/ids.passed"] in [
        one.argv for one in cyber_range.nodes["sensor"].sent]


def test_a_terminal_reload_is_recorded_with_the_passed_test_of_its_files(as_defender, board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)
    tested = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()

    cyber_range.gateway.edited(HTTP, DENY, reloaded=True)
    service.record_terminal_reload(board_round)

    head = service.versions(board_round, "waf")[-1]
    assert head.source == "terminal" and head.tested_id == tested["test"] and head.same_as_tested is True
