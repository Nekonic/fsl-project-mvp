import pytest

from cr import errors
from telemetry.models import Event
from training.defence import rules as service
from tests.training.defence.conftest import BASELINE, LOGIN_RULE, SEARCH_RULE

SETUP_FILE = "/etc/nginx/modsecurity/crs/crs-setup.conf"
EXCLUSIONS = "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
HTTP = "/etc/nginx/defence/http.conf"
EXCLUDE_Q = ('SecRule REQUEST_FILENAME "@beginsWith /search/" '
             '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=942100;ARGS:q"\n')

BASE = "/api/rounds/{round}/defence/"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def test_reading_the_rules_before_any_apply_shows_the_live_file_at_version_zero(as_defender, board_round):
    answer = as_defender.get(url(board_round, "ids/rules/"))

    assert answer.status_code == 200
    assert answer.json() == {"text": BASELINE, "version": 0, "recorded": False}


@pytest.mark.parametrize("method, tail", [("post", "ids/rules/apply/"), ("post", "ids/rules/check/"),
                                          ("get", "ids/disabled/"), ("post", "ids/disabled/"),
                                          ("delete", "ids/disabled/9000001/")])
def test_the_ids_rules_are_changed_on_the_sensor_not_through_the_api(as_defender, board_round, cyber_range, method,
                                                                     tail):
    answer = getattr(as_defender, method)(url(board_round, tail), {"text": SEARCH_RULE, "base_version": 0},
                                          format="json")

    assert answer.status_code == 404
    assert cyber_range.sensors["sensor"].rules == BASELINE


def test_a_posture_a_second_sensor_refuses_rolls_the_first_back_and_records_nothing(board_round, two_sensors):
    service.apply_ids(board_round, SEARCH_RULE, 0)
    two_sensors.sensors["sensor2"].reload_fails = True

    with pytest.raises(errors.EngineRefused) as refused:
        service.apply_ids(board_round, LOGIN_RULE, 1)

    assert refused.value.code == "apply_refused"
    assert [(sensor["name"], sensor["ok"]) for sensor in refused.value.params["sensors"]] == [
        ("cr-ids", False), ("cr-ids2", False)]
    assert two_sensors.sensors["sensor"].rules == SEARCH_RULE == two_sensors.sensors["sensor2"].rules
    assert [one.version for one in service.versions(board_round, "ids")] == [1]


def test_a_named_test_must_be_this_player_s_test_of_this_engine(as_defender, board_round):
    ids_test = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").json()

    wrong = as_defender.post(url(board_round, "waf/apply/"),
                             {"files": {HTTP: "deny 203.0.113.9;\n"}, "base_version": 0, "tested": ids_test["test"]},
                             format="json")

    assert wrong.status_code == 400
    assert wrong.json()["errors"] == [{"path": "tested", "code": "does_not_exist"}]


def test_the_waf_files_are_written_reloaded_and_recorded_as_a_version_with_their_text_and_hash(as_defender,
                                                                                               board_round,
                                                                                               cyber_range):
    answer = as_defender.post(url(board_round, "waf/apply/"),
                              {"files": {EXCLUSIONS: EXCLUDE_Q}, "base_version": 0}, format="json")

    assert answer.status_code == 200 and answer.json()["version"] == 1
    assert cyber_range.gateway.files[EXCLUSIONS] == EXCLUDE_Q
    assert cyber_range.gateway.workers == 2
    shown = as_defender.get(url(board_round, "waf/")).json()
    assert {one["path"]: one["text"] for one in shown["files"]}[EXCLUSIONS] == EXCLUDE_Q
    assert shown["version"] == 1 and shown["recorded"] is True and shown["sha"] == answer.json()["sha"]
    stored = as_defender.get(url(board_round, "waf/versions/1/")).json()
    assert stored["source"] == "console" and stored["sha"] == shown["sha"]
    assert {one["path"]: one["text"] for one in stored["files"]} == {one["path"]: one["text"] for one in shown["files"]}


def test_a_stale_waf_apply_is_refused(as_defender, board_round, cyber_range):
    as_defender.post(url(board_round, "waf/apply/"), {"files": {EXCLUSIONS: EXCLUDE_Q}, "base_version": 0},
                     format="json")

    answer = as_defender.post(url(board_round, "waf/apply/"), {"files": {EXCLUSIONS: ""}, "base_version": 0},
                              format="json")

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["params"] == {"current_version": 1}
    assert cyber_range.gateway.files[EXCLUSIONS] == EXCLUDE_Q


def test_files_nginx_refuses_on_reload_are_rolled_back_and_refused_with_the_file_and_line(as_defender, board_round,
                                                                                        cyber_range):
    before = dict(cyber_range.gateway.files)
    cyber_range.gateway.reload_fails = 'unknown directive "denyy"'

    answer = as_defender.post(url(board_round, "waf/apply/"), {"files": {HTTP: "denyy all;\n"}, "base_version": 0},
                              format="json")

    assert answer.status_code == 422
    assert answer.json()["errors"] == [{"path": HTTP, "code": "crs_refused", "line": 2,
                                        "params": {"message": 'unknown directive "denyy"'}}]
    assert cyber_range.gateway.files == before
    assert as_defender.get(url(board_round, "waf/versions/")).json() == []


@pytest.mark.parametrize("files, path, named", [
    ({"/etc/nginx/nginx.conf": "events {}\n"}, "/etc/nginx/nginx.conf", "not one the defence edits"),
    ({HTTP: "access_log off;\n"}, HTTP, "access_log"),
    ({SETUP_FILE: "SecAuditEngine Off\n"}, SETUP_FILE, "SecAuditEngine"),
])
def test_a_file_the_defence_does_not_edit_or_the_platform_s_logging_never_reaches_the_waf(as_defender, board_round,
                                                                                        cyber_range, files, path,
                                                                                        named):
    before = dict(cyber_range.gateway.files)

    answer = as_defender.post(url(board_round, "waf/apply/"), {"files": files, "base_version": 0}, format="json")

    assert answer.status_code == 422
    assert [(one["path"], one["code"]) for one in answer.json()["errors"]] == [(path, "crs_refused")]
    assert named in answer.json()["errors"][0]["params"]["message"]
    assert cyber_range.gateway.files == before


def test_the_rule_engine_may_be_turned_off_the_score_shows_the_result(as_defender, board_round, cyber_range):
    answer = as_defender.post(url(board_round, "waf/apply/"),
                              {"files": {SETUP_FILE: "SecRuleEngine Off\n"}, "base_version": 0}, format="json")

    assert answer.status_code == 200
    assert cyber_range.gateway.files[SETUP_FILE] == "SecRuleEngine Off\n"
