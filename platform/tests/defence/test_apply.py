from events.models import Event
from tests.defence.conftest import BASELINE, LOGIN_RULE, SEARCH_RULE

BASE = "/api/rounds/{round}/defence/"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def test_reading_the_rules_before_any_apply_shows_the_live_file_at_version_zero(as_defender, board_round):
    answer = as_defender.get(url(board_round, "ids/rules/"))

    assert answer.status_code == 200
    assert answer.json() == {"text": BASELINE, "version": 0}


def test_an_apply_writes_every_sensor_and_records_a_new_version(as_defender, board_round, two_sensors):
    answer = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0},
                              format="json")

    assert answer.status_code == 200
    assert answer.json()["version"] == 1
    assert answer.json()["sensors"] == [{"name": "cr-ids", "ok": True}, {"name": "cr-ids2", "ok": True}]
    assert two_sensors.sensors["sensor"].rules == SEARCH_RULE
    assert two_sensors.sensors["sensor2"].rules == SEARCH_RULE
    assert as_defender.get(url(board_round, "ids/rules/")).json() == {"text": SEARCH_RULE, "version": 1}
    assert Event.objects.filter(round_id=board_round.pk, kind="rule.applied").get().body == {"engine": "ids",
                                                                                             "version": 1}


def test_an_apply_on_a_stale_base_is_refused_with_the_current_version_and_writes_nothing(as_defender, board_round,
                                                                                         cyber_range):
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0}, format="json")
    written = len(cyber_range.sensors["sensor"].sent)

    answer = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": LOGIN_RULE, "base_version": 0},
                              format="json")

    assert answer.status_code == 409
    assert answer.json() == {"errors": [{"path": "", "code": "stale_version", "params": {"current_version": 1}}]}
    assert cyber_range.sensors["sensor"].rules == SEARCH_RULE
    assert len(cyber_range.sensors["sensor"].sent) == written


def test_a_sensor_that_refuses_rolls_back_the_sensors_already_written_to_the_previous_head(as_defender, board_round,
                                                                                          two_sensors):
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0}, format="json")
    two_sensors.sensors["sensor2"].reload_fails = True

    answer = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": LOGIN_RULE, "base_version": 1},
                              format="json")

    assert answer.status_code == 422
    refused = answer.json()["errors"][0]
    assert refused["code"] == "apply_refused"
    assert [(sensor["name"], sensor["ok"]) for sensor in refused["params"]["sensors"]] == [
        ("cr-ids", False), ("cr-ids2", False)]
    assert two_sensors.sensors["sensor"].rules == SEARCH_RULE
    assert two_sensors.sensors["sensor2"].rules == SEARCH_RULE
    assert as_defender.get(url(board_round, "ids/rules/")).json()["version"] == 1


def test_rules_the_sensor_cannot_parse_are_refused_with_their_lines_before_anything_is_written(as_defender,
                                                                                              board_round,
                                                                                              cyber_range):
    cyber_range.sensors["sensor"].syntax = {1: "bad option"}

    answer = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": "alert nonsense (sid:5;)\n",
                                                                       "base_version": 0}, format="json")

    assert answer.status_code == 422
    assert answer.json()["errors"][0]["code"] == "suricata_syntax"
    assert answer.json()["errors"][0]["line"] == 1
    assert cyber_range.sensors["sensor"].rules == BASELINE


def test_a_rule_without_a_sid_the_platform_can_read_is_refused_as_unread(as_defender, board_round, cyber_range):
    answer = as_defender.post(url(board_round, "ids/rules/apply/"),
                              {"text": SEARCH_RULE + 'alert http any any -> any any (msg:"no id";)\n',
                               "base_version": 0}, format="json")

    assert answer.status_code == 422
    assert answer.json()["errors"] == [{"path": "text", "code": "unread_sid", "line": 2,
                                        "params": {"message": 'alert http any any -> any any (msg:"no id";)'}}]
    assert cyber_range.sensors["sensor"].rules == BASELINE


def test_the_applied_version_says_whether_it_is_the_text_that_was_tested(as_defender, board_round):
    tested = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").json()

    same = as_defender.post(url(board_round, "ids/rules/apply/"),
                            {"text": SEARCH_RULE, "base_version": 0, "tested": tested["test"]}, format="json")
    changed = as_defender.post(url(board_round, "ids/rules/apply/"),
                               {"text": LOGIN_RULE, "base_version": 1, "tested": tested["test"]}, format="json")

    assert same.json()["same_as_tested"] is True
    assert changed.json()["same_as_tested"] is False
    assert [(one["version"], one["tested"], one["same_as_tested"]) for one in
            as_defender.get(url(board_round, "ids/rules/versions/")).json()] == [
        (1, tested["test"], True), (2, tested["test"], False)]


def test_an_apply_need_not_be_tested_but_a_named_test_must_be_this_seat_s_test_of_this_engine(as_defender,
                                                                                              board_round):
    waf_test = as_defender.post(url(board_round, "waf/test/"), {"posture": {"paranoia": 2}}, format="json").json()

    untested = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0},
                                format="json")
    wrong = as_defender.post(url(board_round, "ids/rules/apply/"),
                             {"text": SEARCH_RULE, "base_version": 1, "tested": waf_test["test"]}, format="json")

    assert untested.status_code == 200 and untested.json()["same_as_tested"] is False
    assert wrong.status_code == 400
    assert wrong.json()["errors"] == [{"path": "tested", "code": "does_not_exist"}]


def test_the_waf_posture_is_applied_as_structured_tuning_and_versioned(as_defender, board_round, cyber_range):
    posture = {"paranoia": 3, "exclusions": [{"rule_id": 942100, "target": "ARGS:q", "path": "/search/"}]}

    answer = as_defender.post(url(board_round, "waf/apply/"), {"posture": posture, "base_version": 0}, format="json")

    assert answer.status_code == 200 and answer.json()["version"] == 1
    assert "blocking_paranoia_level=3" in cyber_range.gateway.file
    assert as_defender.get(url(board_round, "waf/")).json() == {
        "posture": {"paranoia": 3, "exclusions": [{"rule_id": 942100, "target": "ARGS:q", "path": "/search/"}]},
        "version": 1}


def test_a_stale_waf_apply_is_refused(as_defender, board_round, cyber_range):
    as_defender.post(url(board_round, "waf/apply/"), {"posture": {"paranoia": 2}, "base_version": 0}, format="json")

    answer = as_defender.post(url(board_round, "waf/apply/"), {"posture": {"paranoia": 4}, "base_version": 0},
                              format="json")

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["params"] == {"current_version": 1}
    assert "blocking_paranoia_level=2" in cyber_range.gateway.file


def test_a_posture_the_validator_refuses_never_reaches_the_waf(as_defender, board_round, cyber_range):
    answer = as_defender.post(url(board_round, "waf/apply/"), {"posture": {"paranoia": 9}, "base_version": 0},
                              format="json")

    assert answer.status_code == 422
    assert answer.json()["errors"][0]["code"] == "crs_refused"
    assert cyber_range.gateway.file == ""
