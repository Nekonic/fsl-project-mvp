from datetime import timedelta

from defence import service
from events.models import Event
from range.runner import Ran
from tests.defence.conftest import BASELINE, SEARCH_RULE

BASE = "/api/rounds/{round}/defence/"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def test_disabling_a_rule_comments_it_out_on_every_sensor_as_a_new_version(as_defender, board_round, two_sensors):
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": BASELINE + SEARCH_RULE, "base_version": 0},
                     format="json")

    answer = as_defender.post(url(board_round, "ids/disabled/"), {"sid": 1001, "minutes": 30, "reason": "noisy"},
                              format="json")

    assert answer.status_code == 201 and answer.json()["sid"] == 1001
    for sensor in two_sensors.sensors.values():
        assert "#alert http any any -> any any (msg:\"SQL injection in search\"" in sensor.rules
        assert "sid:9000001" in sensor.rules
    assert as_defender.get(url(board_round, "ids/rules/")).json()["version"] == 2
    assert as_defender.get(url(board_round, "ids/disabled/")).json() == [
        {"sid": 1001, "original": SEARCH_RULE.strip(), "reason": "noisy", "expires_at": answer.json()["expires_at"]}]
    assert Event.objects.filter(round_id=board_round.pk, kind="rule.disabled").get().body["sid"] == 1001


def test_enabling_puts_the_rule_back_and_drops_it_from_the_disabled_list(as_defender, board_round, cyber_range):
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": BASELINE + SEARCH_RULE, "base_version": 0},
                     format="json")
    as_defender.post(url(board_round, "ids/disabled/"), {"sid": 1001, "minutes": 30}, format="json")

    answer = as_defender.delete(url(board_round, "ids/disabled/1001/"))

    assert answer.status_code == 204
    assert cyber_range.sensors["sensor"].rules == BASELINE + SEARCH_RULE
    assert as_defender.get(url(board_round, "ids/disabled/")).json() == []
    assert as_defender.delete(url(board_round, "ids/disabled/1001/")).status_code == 404


def test_a_sid_no_active_rule_carries_cannot_be_disabled(as_defender, board_round):
    answer = as_defender.post(url(board_round, "ids/disabled/"), {"sid": 4242, "minutes": 5}, format="json")

    assert answer.status_code == 404
    assert answer.json()["errors"] == [{"path": "sid", "code": "not_found"}]


def test_a_disable_past_its_time_is_enabled_again(as_defender, board_round, cyber_range):
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": BASELINE + SEARCH_RULE, "base_version": 0},
                     format="json")
    made = service.disable_rule(board_round, 1001, 5)

    assert service.enable_expired(board_round, made.expires_at - timedelta(seconds=1)) == []
    assert service.enable_expired(board_round, made.expires_at + timedelta(seconds=1)) == [1001]
    assert cyber_range.sensors["sensor"].rules == BASELINE + SEARCH_RULE


def test_a_live_crs_file_that_differs_from_the_head_posture_is_drift_reported_once(as_defender, board_round,
                                                                                  cyber_range, at):
    as_defender.post(url(board_round, "waf/apply/"), {"posture": {"paranoia": 2}, "base_version": 0}, format="json")

    assert service.check_drift(board_round, at) is False
    assert service.posture_drift(board_round) is False

    cyber_range.gateway.file += 'SecAction "id:10999,phase:1,pass,nolog,ctl:ruleEngine=Off"\n'

    assert service.check_drift(board_round, at) is True
    assert service.check_drift(board_round, at) is True
    assert service.posture_drift(board_round) is True
    drifted = Event.objects.filter(round_id=board_round.pk, kind="rule.drifted")
    assert [(event.body, event.seat_side) for event in drifted] == [({"engine": "waf"}, "defence")]


def test_a_round_with_no_applied_posture_has_nothing_to_drift_from(board_round, cyber_range, at):
    cyber_range.gateway.file = "anything"

    assert service.check_drift(board_round, at) is False


def test_a_waf_the_platform_cannot_read_is_not_reported_as_drift(as_defender, board_round, cyber_range, at):
    as_defender.post(url(board_round, "waf/apply/"), {"posture": {"paranoia": 2}, "base_version": 0}, format="json")

    def unreachable(argv, stdin=None, timeout=60.0):
        return Ran(255, "ssh: connect to host refused")

    cyber_range.gateway = unreachable

    assert service.check_drift(board_round, at) is False
    assert service.posture_drift(board_round) is False
    assert not Event.objects.filter(round_id=board_round.pk, kind="rule.drifted").exists()
