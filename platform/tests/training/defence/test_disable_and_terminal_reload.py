from datetime import timedelta

from sandbox.runner import Ran
from telemetry.models import Event
from tests.training.defence.conftest import BASELINE, SEARCH_RULE
from training.defence import rules as service

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"


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


def test_a_reload_done_in_the_terminal_is_recorded_as_the_next_version_on_the_next_read(as_defender, board_round,
                                                                                         defender, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    cyber_range.gateway.edited(HTTP, "deny 203.0.113.9;\n", reloaded=True)

    assert service.record_terminal_reload(board_round) is True
    assert service.record_terminal_reload(board_round) is False, "the same running files are one version"
    stored = service.versions(board_round, "waf")
    assert [(one.version, one.source) for one in stored] == [(1, "setup"), (2, "terminal")]
    assert stored[-1].files[HTTP] == "deny 203.0.113.9;\n" and stored[-1].player == defender
    applied = Event.objects.filter(round_id=board_round.pk, kind="rule.applied").order_by("id").last()
    assert (applied.body, applied.player_side) == ({"engine": "waf", "version": 2, "source": "terminal"}, "defence")
    shown = as_defender.get(url(board_round, "waf/")).json()
    assert shown["version"] == 2 and shown["recorded"] is True


def test_files_edited_but_not_reloaded_are_not_running_and_are_not_recorded(as_defender, board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    cyber_range.gateway.edited(HTTP, "deny 203.0.113.9;\n", reloaded=False)

    assert service.record_terminal_reload(board_round) is False
    assert [one.version for one in service.versions(board_round, "waf")] == [1]
    shown = as_defender.get(url(board_round, "waf/")).json()
    assert {one["path"]: one["text"] for one in shown["files"]}[HTTP] == "deny 203.0.113.9;\n"
    assert shown["recorded"] is False


def test_a_round_with_no_recorded_version_has_nothing_to_compare_a_reload_with(board_round, cyber_range):
    cyber_range.gateway.edited(HTTP, "deny all;\n", reloaded=True)

    assert service.record_terminal_reload(board_round) is False


def test_a_waf_the_platform_cannot_read_records_nothing(board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    def unreachable(argv, stdin=None, timeout=60.0):
        return Ran(255, "ssh: connect to host refused")

    cyber_range.gateway = unreachable

    assert service.record_terminal_reload(board_round) is False
    assert [one.version for one in service.versions(board_round, "waf")] == [1]
